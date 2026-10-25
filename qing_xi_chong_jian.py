# -*- coding: utf-8 -*-
# ============================================
# 数据清洗与重建迁移工具（2026-10 新架构数据迁移）
#
# 对应"清洗 + 重建"策略的四步：
#   1. 扫描旧文件夹结构，按文件类型白名单筛选（--dry-run）
#   2. 有效文件物理迁移到"按年份扁平存储"目录（--migrate）
#   3. 原文件夹层级路径转换为文件初始标签（--migrate 时写入）
#   4. 触发新解析管线批量重解析和向量化（--reparse）
#
# 白名单规则：
#   文档类(docx/xlsx/pptx/pdf/txt/md/csv)  深度解析：全文提取 -> DeepSeek -> 向量
#   图片类(jpg/png/gif/bmp/webp)           视觉解析：本地视觉模型描述 -> DeepSeek -> 向量
#   视频类(mp4/m4v/avi/mkv/mov/wmv/flv/rmvb) 仅元数据：时长/分辨率(box解析) -> 不调AI、不解析内容
#   Visio/老Office(doc/ppt/xls/wps/et)     保留+标签：本机无全文提取手段，文件名+标签入向量
#   压缩包(zip/rar/7z/tar/gz/iso)          隔离：移入 99-回收站\清洗隔离-日期\（不真删，可找回）
#   其他(psd/dwg/py/损坏等)                隔离：同上
#
# 用法：
#   python qing_xi_chong_jian.py --dry-run          # 只扫描出报告（只读，默认）
#   python qing_xi_chong_jian.py --migrate --yes    # 移动+隔离+数据库路径改写+初始标签
#   python qing_xi_chong_jian.py --chong-zhi --yes  # 重置解析数据(放弃旧解析结果)+清向量库
#   python qing_xi_chong_jian.py --reparse --yes    # 全量重解析(幂等可续跑)
#   python qing_xi_chong_jian.py --all --yes        # 以上全部
#   --gen PATH  指定文档库根目录（默认 config.WEN_DANG_KU；演练用）
# ============================================

import argparse
import datetime
import json
import os
import re
import struct
import sys
import time

XIANG_MU_GEN = os.path.dirname(os.path.abspath(__file__))
if XIANG_MU_GEN not in sys.path:
    sys.path.insert(0, XIANG_MU_GEN)

import config
from app.gong_ju import wen_jian_ti_qu, tupian_shibie, deepseek_api

# ---------- 白名单 ----------
WEN_DANG_KZM = {".docx", ".xlsx", ".xlsm", ".pptx", ".pdf", ".txt", ".md", ".csv"}
TU_PIAN_KZM = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
SHI_PIN_KZM = {".mp4", ".m4v", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".rmvb"}
# 保留但本机提不了全文：视频同级处理（元数据+标签，不进AI）
YUAN_SHU_JU_KZM = {".vsd", ".vsdx", ".doc", ".ppt", ".xls", ".wps", ".et"}
YA_SUO_KZM = {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"}

DONG_SHEN_DU = "shen_du"            # 深度解析
DONG_SHI_JUE = "shi_jue"            # 视觉解析
DONG_YUAN_SHU_JU = "yuan_shu_ju"    # 仅元数据
DONG_GE_LI = "ge_li"                # 隔离（回收站）

DONG_ZUO_MING = {
    DONG_SHEN_DU: "深度解析(全文提取+AI)",
    DONG_SHI_JUE: "视觉解析(图片描述+AI)",
    DONG_YUAN_SHU_JU: "仅元数据(保留不解析)",
    DONG_GE_LI: "隔离(移入回收站)",
}

# 扫描时跳过的系统目录前缀
TIAO_GUO_MULU = ("99-", "00-收件箱")

RI_QI_ZHENG_ZE = re.compile(r"(20\d{6})")


def pan_duan_dong_zuo(kuo_zhan_ming: str, da_xiao: int) -> str:
    """按扩展名和大小判定文件动作。0字节视为损坏隔离。"""
    if da_xiao == 0:
        return DONG_GE_LI
    if kuo_zhan_ming in WEN_DANG_KZM:
        return DONG_SHEN_DU
    if kuo_zhan_ming in TU_PIAN_KZM:
        return DONG_SHI_JUE
    if kuo_zhan_ming in SHI_PIN_KZM:
        return DONG_YUAN_SHU_JU
    if kuo_zhan_ming in YUAN_SHU_JU_KZM:
        return DONG_YUAN_SHU_JU
    return DONG_GE_LI


def ji_suan_nian_fen(abs_p: str, wen_jian_ming: str) -> str:
    """年份归属：文件名里的8位日期(校验合法) > 文件修改时间。"""
    m = RI_QI_ZHENG_ZE.search(os.path.splitext(wen_jian_ming)[0])
    if m:
        d = m.group(1)
        try:
            if 1 <= int(d[4:6]) <= 12 and 1 <= int(d[6:8]) <= 31:
                return d[:4]
        except ValueError:
            pass
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(abs_p)).strftime("%Y")
    except OSError:
        return datetime.datetime.now().strftime("%Y")


def he_bing_biao_qian(*lai_yuan: str) -> str:
    """多个标签串合并去重（中英文逗号/分号/顿号分隔），最多留10个。"""
    seen, out = set(), []
    for s in lai_yuan:
        for t in re.split(r"[,，;；、]", s or ""):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return ",".join(out[:10])


def lu_jing_zhuan_biao_qian(rel: str) -> str:
    """第三步：原文件夹层级 -> 初始标签。逐段去掉 数字- 前缀（01-工作 -> 工作），
    年份目录（2026 这类）不算分类标签，跳过。"""
    duan = re.split(r"[/\\]", rel)
    biao_qian = []
    for d in duan[:-1]:                       # 最后一段是文件名，不算
        d = re.sub(r"^\d+-", "", d).strip()
        if d and not re.fullmatch(r"20\d\d", d):
            biao_qian.append(d)
    return he_bing_biao_qian(*biao_qian)


def du_mp4_yuan_shu_ju(abs_p: str):
    """best-effort 读 MP4/MOV 元数据：返回 (时长秒, "宽x高")，失败返回 (None, None)。

    自写 box 解析（本机无 ffprobe/cv2）：遍历顶层 box 定位 moov，
    从 mvhd 读时长、tkhd 读分辨率。moov 体只读前64MB，不整读大文件。
    """
    def du_box(f, jie_zhi):
        """从当前位置顺序读 box 头，返回 (type, payload_size, header_end_pos)"""
        while True:
            tou = f.read(8)
            if len(tou) < 8:
                return None, 0, 0
            da_xiao, lei_xing = struct.unpack(">I4s", tou)
            zi_jie = 8
            if da_xiao == 1:                  # largesize
                da_xiao = struct.unpack(">Q", f.read(8))[0]
                zi_jie = 16
            elif da_xiao == 0:                # 到文件结尾
                da_xiao = jie_zhi - f.tell() + 8
            if da_xiao < zi_jie:              # 坏 box，防死循环
                return None, 0, 0
            return lei_xing.decode("latin1"), da_xiao - zi_jie, f.tell()

    try:
        wen_jian_da_xiao = os.path.getsize(abs_p)
        shi_chang, fen_bian_lv = None, None
        with open(abs_p, "rb") as f:
            while f.tell() < wen_jian_da_xiao:
                lei_xing, payload, payload_pos = du_box(f, wen_jian_da_xiao)
                if lei_xing is None:
                    break
                if lei_xing == "moov":
                    moov_shu_ju = f.read(min(payload, 64 * 1024 * 1024))
                    shi_chang, fen_bian_lv = _jie_xi_moov(moov_shu_ju)
                    break
                f.seek(payload_pos + payload)     # 跳过兄弟 box
        return shi_chang, fen_bian_lv
    except Exception:
        return None, None


def _jie_xi_moov(shu_ju: bytes):
    """解析 moov 体里的 mvhd(时长) 和第一个 tkhd(宽高)。"""
    import io
    shi_chang, fen_bian_lv = None, None
    f = io.BytesIO(shu_ju)
    while True:
        tou = f.read(8)
        if len(tou) < 8:
            break
        da_xiao, lei_xing = struct.unpack(">I4s", tou)
        if da_xiao < 8:
            break
        nei_rong = f.read(da_xiao - 8)
        if lei_xing == b"mvhd" and len(nei_rong) >= 4:
            ban_ben = nei_rong[0]
            try:
                if ban_ben == 1 and len(nei_rong) >= 32:
                    shi_jian_chi, shi_chang_zhi = struct.unpack(">IQ", nei_rong[20:32])
                elif ban_ben == 0 and len(nei_rong) >= 20:
                    shi_jian_chi, shi_chang_zhi = struct.unpack(">II", nei_rong[12:20])
                else:
                    shi_jian_chi, shi_chang_zhi = 0, 0
                if shi_jian_chi:
                    shi_chang = round(shi_chang_zhi / shi_jian_chi, 1)
            except struct.error:
                pass
        elif lei_xing == b"trak":
            # trak 体里找 tkhd（跳过头部的 mvhd 式字段，tkhd 尾部固定是 8 字节宽高）
            idx = nei_rong.find(b"tkhd")
            if idx >= 0:
                tkhd = nei_rong[idx:]
                if len(tkhd) >= 8:
                    ban_ben = tkhd[4]
                    # tkhd 完整 box：payload 尾部最后8字节是 width/height（16.16定点）
                    # payload_len = da_xiao-8，位于 tkhd 盒子内偏移 4+(da_xiao-8)-8
                    tkhd_size = struct.unpack(">I", tkhd[:4])[0]
                    wei_zhi = 4 + (tkhd_size - 8) - 8
                    if 0 <= wei_zhi <= len(tkhd) - 8:
                        kuan, gao = struct.unpack(">II", tkhd[wei_zhi:wei_zhi + 8])
                        kuan, gao = kuan >> 16, gao >> 16
                        if kuan and gao:
                            fen_bian_lv = f"{kuan}x{gao}"
        if shi_chang is not None and fen_bian_lv is not None:
            break
    return shi_chang, fen_bian_lv


def _ge_shi_shi_chang(miao) -> str:
    if miao is None:
        return "未知"
    m, s = divmod(int(miao), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------- 第一步：扫描 ----------

def sao_miao(gen: str) -> dict:
    """遍历文档库，产出迁移计划。"""
    bao_liu, ge_li = [], []
    for dp, ds, fs in os.walk(gen):
        ds[:] = [d for d in ds if not d.startswith(TIAO_GUO_MULU)]
        for ming in fs:
            if ming.startswith("~$"):
                continue
            abs_p = os.path.join(dp, ming)
            rel = os.path.relpath(abs_p, gen)
            try:
                da_xiao = os.path.getsize(abs_p)
            except OSError:
                continue
            if ming == "文件索引总表.xlsx":
                dong_zuo, li_you = DONG_GE_LI, "旧系统索引导出表"
            else:
                dong_zuo = pan_duan_dong_zuo(os.path.splitext(ming)[1].lower(), da_xiao)
                li_you = ""
                if dong_zuo == DONG_GE_LI and da_xiao == 0:
                    li_you = "0字节/损坏"
            xiang = {
                "rel": rel,
                "name": ming,
                "kzm": os.path.splitext(ming)[1].lower(),
                "dong_zuo": dong_zuo,
                "li_you": li_you,
                "da_xiao": da_xiao,
                "biao_qian": lu_jing_zhuan_biao_qian(rel),
            }
            if dong_zuo == DONG_GE_LI:
                ge_li.append(xiang)
            else:
                xiang["nian_fen"] = ji_suan_nian_fen(abs_p, ming)
                bao_liu.append(xiang)
    return {"bao_liu": bao_liu, "ge_li": ge_li}


def xie_bao_gao(gen: str, plan: dict) -> str:
    """写 dry-run 报告（txt + json），返回 txt 路径。"""
    shi_jian = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)
    json_lu = os.path.join(config.RI_ZHI_MU_LU, f"qing_xi_bao_gao_{shi_jian}.json")
    with open(json_lu, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)

    from collections import Counter
    tong_ji_dz = Counter(x["dong_zuo"] for x in plan["bao_liu"])
    tong_ji_nf = Counter(x["nian_fen"] for x in plan["bao_liu"])
    tong_ji_kzm = Counter(x["kzm"] for x in plan["bao_liu"] + plan["ge_li"])
    # 同年份重名预测
    chong_ming = Counter((x["nian_fen"], x["name"]) for x in plan["bao_liu"])

    hang = [f"# 清洗重建 dry-run 报告  {shi_jian}", f"# 文档库: {gen}", "",
            f"保留 {len(plan['bao_liu'])} 个，隔离 {len(plan['ge_li'])} 个", ""]
    hang.append("== 按动作 ==")
    for dz, n in tong_ji_dz.most_common():
        hang.append(f"  {DONG_ZUO_MING[dz]}: {n}")
    hang.append("")
    hang.append("== 按年份 ==")
    for nf in sorted(tong_ji_nf):
        hang.append(f"  {nf}: {tong_ji_nf[nf]}")
    hang.append("")
    hang.append("== 按扩展名 ==")
    for kzm, n in tong_ji_kzm.most_common():
        hang.append(f"  {kzm or '(无扩展名)'}: {n}")
    yu_ji = [k for k, n in chong_ming.items() if n > 1]
    hang += ["", f"== 同年份重名 {len(yu_ji)} 组（迁移时自动加 _2 后缀）=="]
    for nf, ming in yu_ji:
        hang.append(f"  {nf}\\{ming} x{chong_ming[(nf, ming)]}")
    hang += ["", f"== 隔离清单 {len(plan['ge_li'])} 个 =="]
    for x in plan["ge_li"]:
        ly = f"    # {x['li_you']}" if x["li_you"] else ""
        hang.append(f"  {x['rel']}{ly}")
    txt_lu = os.path.join(config.RI_ZHI_MU_LU, f"qing_xi_bao_gao_{shi_jian}.txt")
    with open(txt_lu, "w", encoding="utf-8") as f:
        f.write("\n".join(hang))
    return txt_lu


# ---------- 第二步+第三步：迁移 ----------

def _bi_kai_chong_ming(mu_lu: str, ming: str) -> str:
    """目标位置已有同名文件时自动追加 _2 _3（沿用 ming_ming_gui_ze 逻辑）。"""
    if not os.path.exists(os.path.join(mu_lu, ming)):
        return ming
    kzm = os.path.splitext(ming)[1]
    zhu_ti = ming[: len(ming) - len(kzm)]
    i = 2
    while os.path.exists(os.path.join(mu_lu, f"{zhu_ti}_{i}{kzm}")):
        i += 1
    return f"{zhu_ti}_{i}{kzm}"


def _zhao_wen_jian_hang(db, rel: str):
    """按相对路径查 wen_jian 行，兼容正反斜杠两种分隔符的历史数据。"""
    from app.moxing import WenJian
    for bian_ti in {rel, rel.replace("\\", "/"), rel.replace("/", "\\")}:
        hang = db.query(WenJian).filter_by(lu_jing=bian_ti).first()
        if hang is not None:
            return hang
    return None


def qian_yi(plan: dict, gen: str) -> dict:
    """物理迁移 + 数据库路径改写 + 初始标签。返回 old_rel -> new_rel 映射。"""
    from app.moxing import Session, WenJian

    ge_li_mu = os.path.join(gen, "99-回收站",
                            f"清洗隔离-{datetime.datetime.now():%Y%m%d}")
    # 上一轮迁移的映射（按新路径索引）：已迁过的文件复用当时的路径标签，
    # 避免中断续跑时拿"年份目录"当标签，把原始层级标签冲掉
    jiu_ying_she = _du_qu_zui_xin_ying_she()
    ying_she = {}
    yi_dong = yi_ge_li = gai_ming = 0

    db = Session()
    try:
        # ---- 隔离：压缩包/垃圾 -> 回收站 ----
        for x in plan["ge_li"]:
            yuan = os.path.join(gen, x["rel"])
            if not os.path.exists(yuan):
                continue
            os.makedirs(ge_li_mu, exist_ok=True)
            xin_ming = _bi_kai_chong_ming(ge_li_mu, x["name"])
            os.rename(yuan, os.path.join(ge_li_mu, xin_ming))
            # 数据库里的旧记录一并清掉（文件已离开文档库）
            hang = _zhao_wen_jian_hang(db, x["rel"])
            if hang is not None:
                db.delete(hang)
            yi_ge_li += 1

        # ---- 保留：迁入 年份\ 扁平目录 ----
        for x in plan["bao_liu"]:
            yuan = os.path.join(gen, x["rel"])
            if not os.path.exists(yuan):
                continue
            mu_biao_mu = os.path.join(gen, x["nian_fen"])
            # 已在目标年份目录里的不动（幂等，中断续跑不会 _2）
            if os.path.dirname(x["rel"]) == x["nian_fen"]:
                xin_rel = x["rel"]
            else:
                os.makedirs(mu_biao_mu, exist_ok=True)
                xin_ming = _bi_kai_chong_ming(mu_biao_mu, x["name"])
                if xin_ming != x["name"]:
                    gai_ming += 1
                os.rename(yuan, os.path.join(mu_biao_mu, xin_ming))
                xin_rel = os.path.join(x["nian_fen"], xin_ming)
            ying_she[x["rel"]] = {"new_rel": xin_rel, "biao_qian": x["biao_qian"],
                                  "dong_zuo": x["dong_zuo"], "nian_fen": x["nian_fen"]}
            yi_dong += 1

            # ---- 数据库路径改写 + 初始标签（第三步） ----
            jiu_xiang = jiu_ying_she.get(_gui_bing_hua(xin_rel))
            if jiu_xiang is not None and jiu_xiang.get("biao_qian"):
                biao_qian = jiu_xiang["biao_qian"]
                ying_she[x["rel"]]["biao_qian"] = biao_qian
            else:
                biao_qian = x["biao_qian"]
            mtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(os.path.join(gen, xin_rel))).strftime("%Y-%m-%d %H:%M:%S")
            hang = _zhao_wen_jian_hang(db, x["rel"])
            if hang is not None:
                mu_biao_hang = _zhao_wen_jian_hang(db, xin_rel)
                if mu_biao_hang is not None and mu_biao_hang is not hang:
                    db.delete(mu_biao_hang)           # 目标已有记录，避免唯一键冲突
                hang.lu_jing = xin_rel
                hang.wen_jian_ming = os.path.basename(xin_rel)
                hang.fen_lei = x["nian_fen"]
                hang.wen_jian_mtime = mtime
                hang.you_xiang_liang = 0              # 位置变了，向量必须重建
                hang.biao_qian = he_bing_biao_qian(biao_qian, hang.biao_qian)
            # 不在库里的新文件：重解析阶段会建档

        db.commit()
    finally:
        db.close()

    # 映射落盘（重解析阶段用它找初始标签；也是幂等依据）
    shi_jian = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ying_she_lu = os.path.join(config.RI_ZHI_MU_LU, f"qing_xi_ying_she_{shi_jian}.json")
    os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)
    with open(ying_she_lu, "w", encoding="utf-8") as f:
        json.dump({"gen": gen, "ying_she": ying_she}, f, ensure_ascii=False, indent=1)

    # 清理空目录（保护 00-/99- 和年份目录）
    for dp, ds, fs in os.walk(gen, topdown=False):
        for d in ds:
            zheng_ge = os.path.join(dp, d)
            if d.startswith(TIAO_GUO_MULU) or re.fullmatch(r"20\d\d", d):
                continue
            try:
                if not os.listdir(zheng_ge):
                    os.rmdir(zheng_ge)
                    print(f"[清空目录] {os.path.relpath(zheng_ge, gen)}")
            except OSError:
                pass

    print(f"[迁移完成] 移动 {yi_dong}，隔离 {yi_ge_li}，重名自动改名 {gai_ming}")
    print(f"[映射已存] {ying_she_lu}")
    return ying_she


# ---------- 重置（放弃旧解析数据） ----------

def chong_zhi_shu_ju() -> None:
    """清 wen_jian 的摘要/标签/向量标记 + 清体检旧数据 + 删 Chroma 集合。"""
    from app.moxing import Session, WenJian, TiJianJieGuo
    from app.gong_ju import xiang_liang_ku
    import chromadb

    db = Session()
    try:
        n = db.query(WenJian).update({WenJian.zhai_yao: "", WenJian.biao_qian: "",
                                      WenJian.wen_zhong: "", WenJian.nian_fen: 0,
                                      WenJian.fa_wen_dan_wei: "", WenJian.you_xiao: "",
                                      WenJian.you_xiang_liang: 0, WenJian.you_fen_kuai: 0})
        n_tj = db.query(TiJianJieGuo).delete()
        db.commit()
        print(f"[重置] wen_jian {n} 行解析数据已清空；ti_jian {n_tj} 行旧待审数据已删")
    finally:
        db.close()

    try:
        ke_hu = chromadb.PersistentClient(path=config.CHROMA_LU_JING)
        ke_hu.delete_collection("wen_dang")
    except Exception:
        pass
    xiang_liang_ku._collection = None        # 强制下次重新打开集合
    print("[重置] Chroma 向量集合已清空")


def fu_wei_wei_wan_cheng() -> int:
    """把"没解析出摘要"的记录向量标记复位（识别失败的图片/提取失败/AI失败的文档），
    强制 --reparse 重做。成功的记录都有摘要（AI或规则给的），不会误伤。"""
    from app.moxing import Session, WenJian
    db = Session()
    try:
        rows = db.query(WenJian).filter(
            WenJian.you_xiang_liang == 1, WenJian.zhai_yao == "").all()
        for r in rows:
            r.you_xiang_liang = 0
        db.commit()
        print(f"[复位] {len(rows)} 条未成功解析的记录已标记重做")
        return len(rows)
    finally:
        db.close()


# ---------- 第四步：重解析 ----------

def fen_xi_wen_jian(rel: str, abs_p: str, chu_shi_biao_qian: str = "") -> dict:
    """单文件解析（纯计算，不落库不建向量）。

    返回: {dong_zuo, wen_ben, zhai_yao, biao_qian, xiang_liang_wen_ben, shi_bai}
    """
    kzm = os.path.splitext(rel)[1].lower()
    ming = os.path.basename(rel)
    if kzm in WEN_DANG_KZM:
        dong_zuo = DONG_SHEN_DU
    elif kzm in TU_PIAN_KZM:
        dong_zuo = DONG_SHI_JUE
    else:
        dong_zuo = DONG_YUAN_SHU_JU

    wen_ben, zhai_yao, shi_bai = "", "", ""

    if dong_zuo == DONG_SHEN_DU:
        wen_ben = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, zi_shu_shang_xian=2000)
        if wen_ben:
            jie_guo = deepseek_api.sheng_cheng_zhai_yao(ming, wen_ben)
            if jie_guo:
                zhai_yao = (jie_guo.get("zhai_yao") or "")[:200]
                biao_qian_ai = jie_guo.get("biao_qian", "")
            else:
                shi_bai = "DeepSeek摘要失败"
                biao_qian_ai = ""
        else:
            biao_qian_ai = ""
            shi_bai = "全文提取为空"
    elif dong_zuo == DONG_SHI_JUE:
        wen_ben = tupian_shibie.shi_bie_tu_pian(abs_p, yong_tu="jie_xi")
        if wen_ben:
            jie_guo = deepseek_api.sheng_cheng_zhai_yao(ming, wen_ben)
            if jie_guo:
                zhai_yao = (jie_guo.get("zhai_yao") or "")[:200]
                biao_qian_ai = jie_guo.get("biao_qian", "")
            else:
                shi_bai = "DeepSeek摘要失败"
                biao_qian_ai = ""
        else:
            biao_qian_ai = ""
            shi_bai = tupian_shibie.shang_ci_shi_bai_yuan_yin or "图片识别为空"
    else:
        # 仅元数据：视频补时长/分辨率，其余按类型给规则摘要，不进 AI
        biao_qian_ai = ""
        if kzm in SHI_PIN_KZM:
            miao, fen_bian = du_mp4_yuan_shu_ju(abs_p)
            zhai_yao = f"视频文件：{ming}（时长{_ge_shi_shi_chang(miao)}"
            if fen_bian:
                zhai_yao += f"，分辨率{fen_bian}"
            zhai_yao += "）"
        elif kzm in {".vsd", ".vsdx"}:
            zhai_yao = f"流程图/图纸文件：{ming}"
        else:
            zhai_yao = f"Office文档（老格式，未提取全文）：{ming}"

    biao_qian = he_bing_biao_qian(chu_shi_biao_qian, biao_qian_ai)
    mian_bao = os.path.splitext(rel)[0].replace(os.sep, " / ")
    xiang_liang_wen_ben = (f"位置：{mian_bao}\n文件名：{ming}\n标签：{biao_qian}\n内容：{wen_ben}")
    return {"dong_zuo": dong_zuo, "wen_ben": wen_ben, "zhai_yao": zhai_yao,
            "biao_qian": biao_qian, "xiang_liang_wen_ben": xiang_liang_wen_ben,
            "shi_bai": shi_bai}


def chong_xin_jie_xi(gen: str) -> None:
    """第四步：全量重解析 + 向量化。幂等：you_xiang_liang=1 的跳过。"""
    from app.moxing import Session, WenJian
    from app.gong_ju import xiang_liang_ku

    ying_she = _du_qu_zui_xin_ying_she()
    db = Session()
    lie_biao = sao_miao(gen)["bao_liu"]
    db.close()

    tong_ji = {"wan_cheng": 0, "xin_jian": 0, "tiao_guo": 0, "cuo_wu": 0, "ai_shi_bai": 0}
    zong = len(lie_biao)
    print(f"[重解析] 共 {zong} 个文件")
    for i, x in enumerate(lie_biao, 1):
        rel, abs_p = x["rel"], os.path.join(gen, x["rel"])
        db = Session()
        try:
            hang = _zhao_wen_jian_hang(db, rel)
            if hang is not None and hang.you_xiang_liang == 1:
                tong_ji["tiao_guo"] += 1
                db.close()
                continue
            chu_shi_bq = ""
            yuan = ying_she.get(_gui_bing_hua(rel))
            if yuan:
                chu_shi_bq = yuan.get("biao_qian", "")
            elif hang is not None:
                chu_shi_bq = hang.biao_qian or ""

            try:
                jie_guo = fen_xi_wen_jian(rel, abs_p, chu_shi_bq)
            except Exception as e:
                print(f"  [解析失败] {rel}: {e}")
                tong_ji["cuo_wu"] += 1
                db.close()
                continue

            if jie_guo["shi_bai"] and jie_guo["dong_zuo"] != DONG_YUAN_SHU_JU:
                tong_ji["ai_shi_bai"] += 1

            mtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(abs_p)).strftime("%Y-%m-%d %H:%M:%S")
            if hang is not None:
                hang.zhai_yao = jie_guo["zhai_yao"]
                hang.biao_qian = jie_guo["biao_qian"]
                hang.fen_lei = os.path.dirname(rel)
                hang.wen_jian_mtime = mtime
                hang.you_xiang_liang = 1
                hang.geng_xin_shi_jian = datetime.datetime.now()
            else:
                db.add(WenJian(
                    lu_jing=rel, wen_jian_ming=os.path.basename(rel),
                    fen_lei=os.path.dirname(rel), zhai_yao=jie_guo["zhai_yao"],
                    biao_qian=jie_guo["biao_qian"], wen_jian_mtime=mtime,
                    you_xiang_liang=1))
            db.commit()

            try:
                xiang_liang_ku.tian_jia_wen_dang(
                    rel, jie_guo["xiang_liang_wen_ben"],
                    {"wen_jian_ming": os.path.basename(rel), "lu_jing": rel})
            except Exception as e:
                print(f"  [向量失败] {rel}: {e}")
                db2 = Session()
                h2 = _zhao_wen_jian_hang(db2, rel)
                if h2 is not None:
                    h2.you_xiang_liang = 0
                    db2.commit()
                db2.close()

            tong_ji["xin_jian"] += 1
            if jie_guo["dong_zuo"] in (DONG_SHEN_DU, DONG_SHI_JUE):
                time.sleep(0.5)       # 控制 API 频率
        finally:
            if db:
                db.close()
        tong_ji["wan_cheng"] = i
        if i % 20 == 0 or i == zong:
            print(f"  [{i}/{zong}] 新建{tong_ji['xin_jian']} 跳过{tong_ji['tiao_guo']} "
                  f"失败{tong_ji['cuo_wu']} AI/识别失败{tong_ji['ai_shi_bai']}")
    print(f"[重解析完成] {tong_ji}")


def _gui_bing_hua(rel: str) -> str:
    """路径统一成正斜杠，映射查找用。"""
    return rel.replace("\\", "/")


def _du_qu_ying_she_lie_biao() -> dict:
    """读最近一次迁移产生的映射（old_rel -> {new_rel, biao_qian,...}），没有则空字典。"""
    import glob
    wen_jian_lie = sorted(glob.glob(os.path.join(config.RI_ZHI_MU_LU, "qing_xi_ying_she_*.json")))
    if not wen_jian_lie:
        return {}
    try:
        with open(wen_jian_lie[-1], encoding="utf-8") as f:
            return json.load(f).get("ying_she", {})
    except Exception as e:
        print(f"[警告] 映射读取失败（初始标签将只靠库内已有值）: {e}")
        return {}


def _du_qu_zui_xin_ying_she() -> dict:
    """返回 new_rel(正斜杠) 为键的映射索引（重解析按新路径找初始标签）。"""
    try:
        return {_gui_bing_hua(v["new_rel"]): v
                for v in _du_qu_ying_she_lie_biao().values()}
    except Exception as e:
        print(f"[警告] 映射解析失败: {e}")
        return {}


# ---------- 入口 ----------

def _que_ren(shuo_ming: str, yes: bool) -> bool:
    if yes:
        return True
    print(shuo_ming)
    return input("确认执行请输入 yes: ").strip().lower() == "yes"


def main():
    parser = argparse.ArgumentParser(description="数据清洗与重建迁移工具")
    parser.add_argument("--dry-run", action="store_true", help="只扫描出报告（只读，默认）")
    parser.add_argument("--migrate", action="store_true", help="物理迁移+隔离+数据库改写+初始标签")
    parser.add_argument("--chong-zhi", action="store_true", help="重置解析数据+清向量库")
    parser.add_argument("--reparse", action="store_true", help="全量重解析（幂等可续跑）")
    parser.add_argument("--fu-wei", action="store_true",
                        help="复位未成功解析(摘要为空)的文件，让 --reparse 重做（如识别失败的图片）")
    parser.add_argument("--all", action="store_true", help="migrate + chong-zhi + reparse")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    parser.add_argument("--gen", default=config.WEN_DANG_KU, help="文档库根目录（默认 config.WEN_DANG_KU）")
    args = parser.parse_args()

    gen = os.path.abspath(args.gen)
    if args.fu_wei:
        fu_wei_wei_wan_cheng()
        if not (args.migrate or args.chong_zhi or args.reparse or args.all):
            return

    if not args.migrate and not args.chong_zhi and not args.reparse and not args.all:
        args.dry_run = True

    if args.dry_run:
        print(f"[第一步] 扫描 {gen} ...")
        plan = sao_miao(gen)
        txt_lu = xie_bao_gao(gen, plan)
        bao_liu, ge_li = len(plan["bao_liu"]), len(plan["ge_li"])
        from collections import Counter
        tong_ji = Counter(x["dong_zuo"] for x in plan["bao_liu"])
        print(f"[扫描完成] 保留 {bao_liu}，隔离 {ge_li}")
        for dz, n in tong_ji.most_common():
            print(f"  {DONG_ZUO_MING[dz]}: {n}")
        print(f"[报告] {txt_lu}")
        return

    if args.all:
        args.migrate = args.chong_zhi = args.reparse = True

    if args.migrate:
        if not _que_ren(f"即将迁移文件并隔离垃圾：{gen}", args.yes):
            print("已取消")
            return
        plan = sao_miao(gen)
        txt_lu = xie_bao_gao(gen, plan)
        print(f"[报告] {txt_lu}")
        qian_yi(plan, gen)

    if args.chong_zhi:
        if not _que_ren("即将清空全部摘要/标签/向量标记并删除向量库（放弃旧解析数据）", args.yes):
            print("已取消")
            return
        chong_zhi_shu_ju()

    if args.reparse:
        if not _que_ren(f"即将全量重解析（调 DeepSeek/本地视觉模型，耗时较长）：{gen}", args.yes):
            print("已取消")
            return
        chong_xin_jie_xi(gen)


if __name__ == "__main__":
    main()
