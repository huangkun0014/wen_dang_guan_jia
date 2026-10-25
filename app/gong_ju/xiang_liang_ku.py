# -*- coding: utf-8 -*-
# ============================================
# 矢量库封装：Chroma 存储 + 本地 bge-m3 嵌入（ONNX 版）
#
# 技术选型说明（为什么这么绕）：
#   1. bge-m3 是最适合中文语义检索的开源嵌入模型，但 fastembed 官方
#      一直没有收录它（只有英文 bge 和 bge-small-zh），装 torch 又太重；
#   2. 最终方案：用 Xenova 维护的 bge-m3 ONNX 量化版（transformers.js 同款），
#      直接 onnxruntime 推理 + tokenizers 分词，纯 CPU、离线、内存占用小；
#   3. bge-m3 的稠密向量取 [CLS] 位置的输出并做 L2 归一化（与官方 FlagEmbedding 一致），
#      对短查询效果尤其好；
#   4. 国内 huggingface.co 被墙，模型走 hf-mirror.com 镜像下载（首次已下载到本地，
#      之后完全离线）。
#
# 数据目录：
#   向量数据 -> 项目 shu_ju/chroma
#   模型缓存 -> shu_ju/models/models--Xenova--bge-m3/
# ============================================

import os
import glob
import threading
import numpy as np
import config

_ke_hu = None          # chromadb 客户端
_collection = None     # 文件级集合（每个文件一条向量）
_kuai_collection = None  # 分块集合（每篇文档切成多块，每块一条向量）
_mo_xing = None        # 本地嵌入模型实例（懒加载）
_chu_shi_hua_suo = threading.Lock()   # 懒加载初始化锁（并发线程安全）

# 分块集合名（全量重建时整集合删除）
KUAI_JI_HE = "wen_dang_kuai"

# 单条文本最多向量化多少个 token（截断），中文文档 512 token 已足够覆盖主题
ZUI_DA_TOKEN = 512
# onnx 推理批大小，U9 + 64G 内存 CPU 上 16 比较稳
PI_PI_SIZE = 16


class _BenDiQianRuMoXing:
    """bge-m3 ONNX 量化模型的薄封装：分词 -> 推理 -> CLS 池化 -> L2 归一化。"""

    def __init__(self):
        from tokenizers import Tokenizer
        import onnxruntime as ort

        # 在模型缓存目录里定位 snapshot 下的 onnx 模型和分词器
        gen_mu_lu = os.path.join(config.MO_XING_HUAN_CUN, "models--Xenova--bge-m3")
        kuai_zhao = sorted(glob.glob(os.path.join(gen_mu_lu, "snapshots", "*")))
        if not kuai_zhao:
            raise RuntimeError(f"找不到 bge-m3 模型文件，请检查目录: {gen_mu_lu}")
        gen = kuai_zhao[-1]

        self.fen_ci_qi = Tokenizer.from_file(os.path.join(gen, "tokenizer.json"))
        # enable_truncation 让超长文本直接截断而不是报错
        self.fen_ci_qi.enable_truncation(max_length=ZUI_DA_TOKEN)

        onnx_lu_jing = os.path.join(gen, "onnx", "model_quantized.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(4, (os.cpu_count() or 8) // 2)
        self.hui_hua = ort.InferenceSession(
            onnx_lu_jing, opts, providers=["CPUExecutionProvider"])

    def bian_ma(self, wen_ben_lie_biao):
        """把文本列表编码成向量（numpy 二维数组，已归一化）"""
        shu_ru = self.fen_ci_qi.encode_batch(wen_ben_lie_biao, add_special_tokens=True)
        # 批内变长序列要补齐（padding）成等长矩阵，短序列补 0
        zui_chang = max(len(x.ids) for x in shu_ru)
        ids, mask = [], []
        for x in shu_ru:
            bu = zui_chang - len(x.ids)
            ids.append(x.ids + [0] * bu)
            mask.append(x.attention_mask + [0] * bu)
        ids = np.array(ids, dtype=np.int64)
        mask = np.array(mask, dtype=np.int64)
        shu_chu = self.hui_hua.run(
            None, {"input_ids": ids, "attention_mask": mask})[0]
        # CLS 池化：取每个序列第一个 token（[CLS]）的向量
        cls = shu_chu[:, 0, :].astype(np.float32)
        # L2 归一化，转成单位向量，后面用余弦相似度比较
        return cls / np.linalg.norm(cls, axis=1, keepdims=True)


def _qu_mo_xing():
    """懒加载本地嵌入模型（加锁：批量任务会开线程，避免并发重复加载）。"""
    global _mo_xing
    if _mo_xing is None:
        with _chu_shi_hua_suo:
            if _mo_xing is None:
                _mo_xing = _BenDiQianRuMoXing()
    return _mo_xing


def _qu_collection():
    """懒加载矢量库连接（加锁：并发首次初始化会触发 Chroma 的
    "Could not connect to tenant default_tenant" 报错，必须串行化）。"""
    global _ke_hu, _collection
    if _collection is None:
        with _chu_shi_hua_suo:
            if _collection is None:
                import chromadb
                os.makedirs(config.CHROMA_LU_JING, exist_ok=True)
                _ke_hu = chromadb.PersistentClient(path=config.CHROMA_LU_JING)
                _collection = _ke_hu.get_or_create_collection(
                    name="wen_dang", metadata={"hnsw:space": "cosine"})
    return _collection


def _qu_kuai_collection():
    """懒加载"分块"集合：每个文件按段落切成多块，每块一条向量。
    文件名/标签等元数据在文件级集合里，这里只存正文块，检索到段落再回表。"""
    global _kuai_collection
    _qu_collection()          # 确保客户端已初始化（它自己有锁，这里不能嵌套拿锁）
    if _kuai_collection is None:
        with _chu_shi_hua_suo:
            if _kuai_collection is None:
                _kuai_collection = _ke_hu.get_or_create_collection(
                    name=KUAI_JI_HE, metadata={"hnsw:space": "cosine"})
    return _kuai_collection


def _bian_liang(wen_ben_lie_biao):
    """把文本列表转成向量列表（分批推理，避免一次性占太多内存）"""
    mo_xing = _qu_mo_xing()
    jie_guo = []
    for i in range(0, len(wen_ben_lie_biao), PI_PI_SIZE):
        pi = wen_ben_lie_biao[i:i + PI_PI_SIZE]
        jie_guo.extend(mo_xing.bian_ma(pi).tolist())
    return jie_guo


def tian_jia_wen_dang(wen_dang_id: str, wen_ben: str, yuan_shu_ju: dict):
    """把一个文档的文本存入矢量库（同 id 重复存=覆盖更新）。

    参数:
        wen_dang_id: 唯一标识，用文件相对路径（改名/移动后旧的作废重建）
        wen_ben: 要向量化的文本
        yuan_shu_ju: 随向量一起存的元数据（文件名、分类等），查询时原样带回
    """
    col = _qu_collection()
    xiang_liang = _bian_liang([wen_ben[:8000]])      # 单文件最多向量化前8000字，够用且省内存
    col.upsert(
        ids=[wen_dang_id],
        embeddings=xiang_liang,
        documents=[wen_ben[:8000]],
        metadatas=[{k: str(v)[:500] for k, v in yuan_shu_ju.items()}],
    )


def _qu_tiao_kuan(kuai: str) -> str:
    """从块文本里取条款/章节标识，存进元数据，搜索时可直接引用。

    优先级：第X条 > 第X章/节 > 行首"五、标题" > 行首"（一）标题"。
    """
    import re as _re
    kuai = kuai or ""
    m = _re.search(r"第[一二三四五六七八九十百千0-9０-９]+条", kuai)
    if m:
        return m.group(0)
    m = _re.search(r"第[一二三四五六七八九十百千0-9０-９]+[章节]", kuai)
    if m:
        return m.group(0)
    m = _re.search(r"(?m)^\s*([一二三四五六七八九十]+、[^\n]{2,20})", kuai)
    if m:
        return m.group(1).strip()
    m = _re.search(r"(?m)^\s*(（[一二三四五六七八九十]+）[^\n]{2,20})", kuai)
    if m:
        return m.group(1).strip()
    return ""


def tian_jia_fen_kuai(lu_jing: str, wen_jian_ming: str, kuai_lie_biao: list,
                      wen_zhong: str = ""):
    """重建某个文件的分块向量：先删旧块，再批量写入。kuai_lie_biao 为文本块列表。

    wen_zhong 会随块一起存，供"只搜规章制度"这类过滤使用（改文种不用重嵌入）。
    """
    shan_chu_fen_kuai(lu_jing)
    if not kuai_lie_biao:
        return
    col = _qu_kuai_collection()
    wen_ben_lie = [k[:1200] for k in kuai_lie_biao]
    xiang_liang = _bian_liang(wen_ben_lie)
    col.upsert(
        ids=[f"{lu_jing}::{i}" for i in range(len(wen_ben_lie))],
        embeddings=xiang_liang,
        documents=wen_ben_lie,
        metadatas=[{"lu_jing": lu_jing, "wen_jian_ming": wen_jian_ming,
                    "kuai_hao": str(i), "wen_zhong": wen_zhong or "",
                    "tiao_kuan": _qu_tiao_kuan(k)}
                   for i, k in enumerate(wen_ben_lie)],
    )


def shan_chu_fen_kuai(lu_jing: str):
    """删除某个文件的全部块向量。"""
    try:
        _qu_kuai_collection().delete(where={"lu_jing": lu_jing})
    except Exception:
        pass


def yu_yi_sou_suo_kuai(cha_xun: str, tiao_shu: int = 40, where: dict = None):
    """在分块库上做语义检索。返回 [{lu_jing, wen_jian_ming, pian_duan, ju_li, tiao_kuan}]。

    where 为 Chroma 元数据过滤（如 {"lu_jing": {"$in": [...]}}），用于先限定文种/文件范围。
    """
    col = _qu_kuai_collection()
    zong_shu = col.count()
    if zong_shu == 0:
        return []
    cha_xun_xiang_liang = _bian_liang([cha_xun])
    can_shu = dict(query_embeddings=cha_xun_xiang_liang,
                   n_results=min(tiao_shu, zong_shu))
    if where:
        can_shu["where"] = where
    jie_guo = col.query(**can_shu)
    items = []
    for i in range(len(jie_guo["ids"][0])):
        md = jie_guo["metadatas"][0][i] or {}
        items.append({
            "lu_jing": md.get("lu_jing", ""),
            "wen_jian_ming": md.get("wen_jian_ming", ""),
            "pian_duan": (jie_guo["documents"][0][i] or "")[:400],
            "ju_li": jie_guo["distances"][0][i],
            "tiao_kuan": md.get("tiao_kuan", ""),
        })
    return items


def guan_jian_ci_sou_suo_kuai(cha_xun: str, tiao_shu: int = 40, where: dict = None):
    """在分块库上做关键词检索（精确命中编号/人名/型号等语义容易漏的词）。
    多关键词取并集，最多用前 3 个词，避免扫描太多。where 用法同语义检索。"""
    import re as _re
    col = _qu_kuai_collection()
    if col.count() == 0:
        return []
    ci_lie = [c for c in _re.split(r"[\s,，;；、]+", cha_xun.strip()) if len(c) >= 2][:3]
    if not ci_lie:
        ci_lie = [cha_xun.strip()]
    kan_jian = {}
    for ci in ci_lie:
        if not ci:
            continue
        try:
            can_shu = dict(where_document={"$contains": ci}, limit=tiao_shu,
                           include=["documents", "metadatas"])
            if where:
                can_shu["where"] = where
            jie = col.get(**can_shu)
        except Exception:
            continue
        ids = jie.get("ids") or []
        docs = jie.get("documents") or []
        mds = jie.get("metadatas") or []
        for i, doc_id in enumerate(ids):
            md = (mds[i] if i < len(mds) else None) or {}
            kan_jian[doc_id] = {
                "lu_jing": md.get("lu_jing", ""),
                "wen_jian_ming": md.get("wen_jian_ming", ""),
                "pian_duan": (docs[i] if i < len(docs) else "")[:400],
                "ju_li": None,
                "tiao_kuan": md.get("tiao_kuan", ""),
            }
    return list(kan_jian.values())[:tiao_shu * 2]


def shan_chu_wen_dang(wen_dang_id: str):
    """按 id 删除文件级向量，并同步删掉它的分块向量（文件被删/改名后清理）"""
    try:
        _qu_collection().delete(ids=[wen_dang_id])
    except Exception:
        pass
    shan_chu_fen_kuai(wen_dang_id)


def yu_yi_sou_suo(cha_xun: str, tiao_shu: int = 20, where: dict = None):
    """按意思搜索。返回相关条目列表，相似度越高越相关。

    例: 查"防雷施工通报"能命中标题不含这几个字、但内容讲防雷施工的文件。
    where 为 Chroma 元数据过滤（按文种/路径限定范围）。
    """
    col = _qu_collection()
    cha_xun_xiang_liang = _bian_liang([cha_xun])
    can_shu = dict(query_embeddings=cha_xun_xiang_liang, n_results=tiao_shu)
    if where:
        can_shu["where"] = where
    jie_guo = col.query(**can_shu)
    items = []
    for i in range(len(jie_guo["ids"][0])):
        items.append({
            "id": jie_guo["ids"][0][i],
            "ju_li": jie_guo["distances"][0][i],        # 余弦距离，越小越相关
            "yuan_shu_ju": jie_guo["metadatas"][0][i],
        })
    return items


def ku_zhong_zong_shu() -> int:
    """矢量库现有向量条数"""
    return _qu_collection().count()


def fen_kuai_zong_shu() -> int:
    """分块库现有块数"""
    return _qu_kuai_collection().count()


def quan_bu_ids():
    """矢量库里全部文档 id 列表（完整性检查用）"""
    return _qu_collection().get()["ids"]


def qing_kong_fen_kuai_ku():
    """删掉整个分块集合（全量重建时用）"""
    global _kuai_collection
    try:
        _qu_collection()
        _ke_hu.delete_collection(KUAI_JI_HE)
    except Exception:
        pass
    _kuai_collection = None


def qing_kong_wen_dang_ku():
    """删掉整个文件级集合（全量重建时用）"""
    global _collection
    try:
        _qu_collection()
        _ke_hu.delete_collection("wen_dang")
    except Exception:
        pass
    _collection = None
