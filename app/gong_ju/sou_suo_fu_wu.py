# -*- coding: utf-8 -*-
# ============================================
# 混合搜索服务：语义（分块 + 整篇） + 关键词，RRF 融合排序
# 被网页搜索接口和 AI 接入接口共用
#
# 为什么混合：
#   纯语义对"编号/人名/设备型号"这类精确词容易漏（向量是模糊匹配）；
#   纯关键词对"换个说法"的查询又不行。两路召回后用 RRF（倒数排名融合）合并。
# 分块检索让长文档能精确命中到段落，结果里直接带回"相关片段"。
# ============================================

import os
import re
import config
from app.moxing import Session, WenJian
from app.gong_ju import xiang_liang_ku

RRF_K = 60          # RRF 平滑常数（常用 60）
ZUI_DA_FAN_HUI = 50  # 单次最多返回多少条


def _gui_bing_hua(rel: str) -> str:
    return (rel or "").replace("\\", "/")


# ---------- 同名制度版本标记 ----------

def _gui_fan_biao_ti(ming: str) -> str:
    """把"20260323_示例车辆段安全监督检查管理办法印发通知.pdf"归一成
    "示例车辆段安全监督检查管理办法"，用于识别同名多版本。"""
    s = re.sub(r"^\d{8}_", "", ming or "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"^附件\d+[_\-]?", "", s)
    s = re.sub(r"[（(](试行|暂行|修订版)[)）]", "", s)
    s = re.sub(r"(重新)?(印发|修订|修改|公布|发布)?(通知|通报)$", "", s)
    s = re.sub(r"(修订版|修改版|试行|暂行)$", "", s)
    s = re.sub(r"_\d+$", "", s)          # 重名时系统自动加的 _2/_3，视为同一份
    return s.strip("_- ")


def _wen_jian_ri_qi(ming: str) -> str:
    m = re.match(r"^(\d{8})_", ming or "")
    return m.group(1) if m else ""


def _ban_ben_biao(wen_zhong: str = "规章制度") -> dict:
    """按归一标题归组，返回：
    {标题: {"zui_xin": "YYYYMMDD", "shu": 文件数, "ri_qi": {日期: 该日期文件数}}}
    """
    db = Session()
    try:
        hang = db.query(WenJian.wen_jian_ming).filter(
            WenJian.wen_zhong == wen_zhong).all()
    finally:
        db.close()
    zu = {}
    for (ming,) in hang:
        t = _gui_fan_biao_ti(ming)
        d = _wen_jian_ri_qi(ming)
        x = zu.setdefault(t, {"zui_xin": "", "shu": 0, "ri_qi": {}})
        x["shu"] += 1
        x["ri_qi"][d] = x["ri_qi"].get(d, 0) + 1
        if d > x["zui_xin"]:
            x["zui_xin"] = d
    return zu


# 领域词扩展：短句/口语里只出现一个具体物件时，补上它所属的制度主题，
# 避免"安全帽没扣带子"被语义模型误配到"防溜铁鞋"这类不相干条款。
_KUO_ZHAN_CI = [
    (("安全帽", "防护服", "安全带", "反光背心", "护目镜", "防护手套",
      "劳保用品", "劳动防护"),
     "劳动防护用品 佩戴 使用"),
    (("铁鞋", "脱轨器", "防溜"),
     "防溜防撞专用器材 铁鞋 撤除 使用"),
    (("酒后", "酒驾", "酒精"),
     "机动车 酒精检测 酒后驾驶"),
    (("动火", "焊接", "切割"),
     "动火作业 审批 监护"),
    (("漏检", "漏探"),
     "TFDS 漏检 故障 提交"),
    (("驻站", "联络员", "防护员"),
     "营业线施工 驻站联络员 现场防护员"),
]


def _kuo_zhan_cha_xun(q: str) -> str:
    """命中领域词时，把查询扩展成"原句 + 主题词"，只影响召回，不影响展示。"""
    for ci_lie, kuo in _KUO_ZHAN_CI:
        if any(c in q for c in ci_lie):
            return f"{q} {kuo}"
    return q


# 关键词覆盖度重排用的领域词库（只收对判断"是不是这条"有区分度的词）
_GUAN_JIAN_CI_KU = (
    "劳动防护用品", "防护用品", "安全帽", "防护服", "安全带", "反光背心",
    "护目镜", "防护手套", "劳保用品", "防暑降温", "高温天气", "作业时间",
    "防溜防撞", "防溜", "铁鞋", "脱轨器", "专用器材", "动火作业", "动火",
    "审批", "监护", "焊接", "切割", "营业线施工", "营业线", "驻站联络员",
    "现场防护员", "驻站", "联络员", "防护员", "漏检", "漏探", "TFDS",
    "车钩", "故障", "提交", "酒后驾驶", "酒后", "酒驾", "酒精", "机动车",
    "驾驶", "安全监督检查", "安全检查", "整改", "复查", "闭环", "销号",
    "防洪", "值守", "汛期", "应急", "演练", "培训", "考核", "隐患",
    "排查", "风险管控", "风险", "检修", "维修", "保养", "报废", "台账",
    "记录", "登记",
)

# 同义词：查询里出现左边，就把右边也算作关键词（片段里可能用另一种写法）
_TONG_YI_CI = {
    "撤除": ("安撤", "撤出"),
    "佩戴": ("穿戴", "使用"),
    "穿戴": ("佩戴",),
    "酒后": ("饮酒", "酒精"),
    "漏检": ("漏探",),
    "整改": ("整治",),
    "复查": ("复核",),
}


def _ti_qu_guan_jian_ci(q: str) -> list:
    """从查询里提取用于覆盖度打分的词（领域词 + 同义词 + 型号/编号）。"""
    ci = []
    for t in _GUAN_JIAN_CI_KU:
        if t in q:
            ci.append(t)
    for t, tong in _TONG_YI_CI.items():
        if t in q:
            ci.extend(tong)
    for m in re.findall(r"[A-Za-z]{2,}\d*|\d{4,}", q or ""):
        ci.append(m)
    # 去掉被更长词包含的短词，避免重复计分
    jie = []
    for t in sorted(set(ci), key=len, reverse=True):
        if not any(t != x and t in x for x in jie):
            jie.append(t)
    return jie[:12]


def _fu_gai_du(ci: list, wen: str) -> float:
    if not ci:
        return 0.0
    wen = wen or ""
    return sum(1 for t in ci if t in wen) / len(ci)


def hu_he_sou_suo(q: str, n: int = 20, wen_zhong: str = "",
                  nian_fen: int = None) -> list:
    """混合检索，返回文件级结果（含最佳相关片段）。

    wen_zhong / nian_fen 为元数据过滤：先从台账取出符合条件的路径，
    再让 Chroma 只在这些文件里检索（不用重建向量）。

    返回字段：ming / abs_lu_jing / xiang_dui_lu_jing / zhai_yao / biao_qian /
              qi_ta_gui_kou / pian_duan / tiao_kuan / xiang_si_du / pi_pei_fang_shi / wen_jian_cun_zai
    """
    q = (q or "").strip()
    if not q:
        return []
    n = max(1, min(int(n or 20), ZUI_DA_FAN_HUI))

    # 元数据过滤：先算出允许的文件路径集合
    where = None
    guo_lv_lu_jing = None
    if wen_zhong or nian_fen:
        db = Session()
        try:
            cha = db.query(WenJian.lu_jing)
            if wen_zhong:
                cha = cha.filter(WenJian.wen_zhong == wen_zhong)
            if nian_fen:
                cha = cha.filter(WenJian.nian_fen == int(nian_fen))
            lu_jing_lie = [h.lu_jing for h in cha.all() if h.lu_jing]
        finally:
            db.close()
        if not lu_jing_lie:
            return []
        guo_lv_lu_jing = {_gui_bing_hua(p) for p in lu_jing_lie}
        # Chroma 的 $in 数量太大时退化为检索后过滤
        if len(lu_jing_lie) <= 800:
            where = {"lu_jing": {"$in": lu_jing_lie}}

    q_cha = _kuo_zhan_cha_xun(q)
    kuai_yu = xiang_liang_ku.yu_yi_sou_suo_kuai(q_cha, 40, where=where)        # 分块语义
    kuai_gj = xiang_liang_ku.guan_jian_ci_sou_suo_kuai(q_cha, 40, where=where)  # 分块关键词
    wen_jian_yu = xiang_liang_ku.yu_yi_sou_suo(q_cha, 20, where=where)          # 整篇语义

    rrf = {}
    xin_xi = {}

    def jia(lie, quan_zhong=1.0):
        for rank, it in enumerate(lie, 1):
            key = it.get("lu_jing") or it.get("id")
            if not key:
                continue
            key = _gui_bing_hua(key)
            rrf[key] = rrf.get(key, 0.0) + quan_zhong / (RRF_K + rank)
            xin = xin_xi.setdefault(key, {"pian_duan": "", "ju_li": None, "tiao_kuan": ""})
            if not xin["pian_duan"] and it.get("pian_duan"):
                xin["pian_duan"] = it["pian_duan"]
            if not xin["tiao_kuan"] and it.get("tiao_kuan"):
                xin["tiao_kuan"] = it["tiao_kuan"]
            # 同一文件可能多个块命中，取最接近的那个距离做展示
            if it.get("ju_li") is not None:
                if xin["ju_li"] is None or it["ju_li"] < xin["ju_li"]:
                    xin["ju_li"] = it["ju_li"]

    jia(kuai_yu)             # 分块语义：权重最高，且带片段
    jia(kuai_gj, 0.9)        # 分块关键词：精确词命中
    jia(wen_jian_yu, 0.8)    # 整篇语义：兜底

    # 关键词覆盖度重排：片段里真的出现查询关键词的块加权（解决"语义像、条款不对"）
    guan_jian_ci = _ti_qu_guan_jian_ci(q_cha)
    if guan_jian_ci:
        for key in list(rrf):
            fg = _fu_gai_du(guan_jian_ci, xin_xi.get(key, {}).get("pian_duan", ""))
            if fg:
                rrf[key] *= (1 + 0.8 * fg)

    pai = sorted(rrf.items(), key=lambda kv: -kv[1])
    # 有元数据过滤时再按路径集合兜底筛一遍（$in 超限时会退化为纯应用层过滤）
    if guo_lv_lu_jing is not None:
        pai = [(k, v) for k, v in pai if k in guo_lv_lu_jing]
    # 多取 5 条：给"同名版本合并/重复去重"留余量，最终仍只返回 n 条
    top = pai[:n + 5]
    if not top:
        return []

    # 批量回表拿摘要/标签（一次查询；库里的路径是反斜杠，两种写法都带上）
    rels = [k for k, _ in top]
    bian = set(rels)
    for r in rels:
        bian.add(r.replace("/", "\\"))
    db = Session()
    try:
        hang_di = {_gui_bing_hua(r.lu_jing): r
                   for r in db.query(WenJian).filter(WenJian.lu_jing.in_(bian)).all()}
    finally:
        db.close()

    jie_guo = []
    for rel, _fen in top:
        hang = hang_di.get(rel)
        abs_p = os.path.join(config.WEN_DANG_KU, rel.replace("/", os.sep))
        xin = xin_xi.get(rel, {})
        ju_li = xin.get("ju_li")
        jie_guo.append({
            "ming": os.path.basename(rel),
            "abs_lu_jing": abs_p,
            "xiang_dui_lu_jing": rel.replace("/", os.sep),
            "zhai_yao": (hang.zhai_yao if hang else "") or "",
            "biao_qian": (hang.biao_qian if hang else "") or "",
            "qi_ta_gui_kou": (hang.qi_ta_gui_kou if hang else "") or "",
            "pian_duan": xin.get("pian_duan", ""),
            "tiao_kuan": xin.get("tiao_kuan", ""),
            "wen_zhong": (hang.wen_zhong if hang else "") or "",
            "nian_fen": (hang.nian_fen if hang else 0) or 0,
            "fa_wen_dan_wei": (hang.fa_wen_dan_wei if hang else "") or "",
            "you_xiao": (hang.you_xiao if hang else "") or "",
            "xiang_si_du": round(1 - ju_li, 3) if ju_li is not None else None,
            "pi_pei_fang_shi": "语义" if ju_li is not None else "关键词",
            "wen_jian_cun_zai": os.path.exists(abs_p),
        })

    # 同名制度版本标记：标出最新版/旧版/重复文件，并去掉同标题同日期的一份
    ban_ben = None
    for x in jie_guo:
        if x.get("wen_zhong") != "规章制度":
            continue
        if ban_ben is None:
            ban_ben = _ban_ben_biao("规章制度")
        biao_ti = _gui_fan_biao_ti(x["ming"])
        ri_qi = _wen_jian_ri_qi(x["ming"])
        xin = ban_ben.get(biao_ti, {"zui_xin": ri_qi, "shu": 1, "ri_qi": {ri_qi: 1}})
        x["biao_ti_gui_fan"] = biao_ti
        x["zui_xin_ban"] = (ri_qi == xin["zui_xin"])
        x["zui_xin_ri_qi"] = xin["zui_xin"]
        x["ban_ben_shu"] = xin["shu"]
        x["chong_fu_ban_ben"] = xin["ri_qi"].get(ri_qi, 0) > 1

    # 重复文件优先保留"原名"（不带 _2/_3 后缀）的那份
    you_xuan = {}
    for x in jie_guo:
        if not x.get("chong_fu_ban_ben"):
            continue
        jian = (x["biao_ti_gui_fan"], _wen_jian_ri_qi(x["ming"]))
        mu_qian = you_xuan.get(jian)
        if mu_qian is None or (len(x["ming"]), -(x.get("xiang_si_du") or 0)) < \
                (len(mu_qian["ming"]), -(mu_qian.get("xiang_si_du") or 0)):
            you_xuan[jian] = x

    qu_chong = []
    kan_jian = set()
    for x in jie_guo:
        if x.get("chong_fu_ban_ben"):
            jian = (x["biao_ti_gui_fan"], _wen_jian_ri_qi(x["ming"]))
            if you_xuan.get(jian) is not x:
                continue
            if jian in kan_jian:
                continue
            kan_jian.add(jian)
        qu_chong.append(x)

    # 同名多版本：最新版排到旧版前面（保持其他结果的相对顺序）
    yi_chu = set()
    xin_lie = []
    for x in qu_chong:
        biao_ti = x.get("biao_ti_gui_fan")
        if not biao_ti or (x.get("ban_ben_shu") or 1) <= 1:
            xin_lie.append(x)
            continue
        if biao_ti in yi_chu:
            continue
        yi_chu.add(biao_ti)
        zu = [y for y in qu_chong if y.get("biao_ti_gui_fan") == biao_ti]
        zu.sort(key=lambda y: (not y.get("zui_xin_ban"),
                               -(y.get("xiang_si_du") or 0)))
        xin_lie.extend(zu)

    return xin_lie[:n]
