# -*- coding: utf-8 -*-
# ============================================
# 考核数据查询服务（只读）
#
# 数据源：本机 SQL Server 的 assessment_db 库 → 考核记录 表
# 用途：按条件检索历史考核信息、做统计汇总、找相似案例，
#       供网页"考核查询"页和 MCP（Kimi 等 AI）调用。
#
# 设计原则：
#   1. 只读：本模块只执行 SELECT，不提供任何写操作；
#   2. 白名单：可筛选/分组的字段全部写死在映射表里，值只走绑定变量，不拼 SQL；
#   3. 限量：列表最多 200 条，统计最多 200 组，避免一次拉太多数据。
#
# 主要函数：
#   cha_xun(**tiao_jian)        按条件查考核记录（分页）
#   tong_ji(fen_zu, **tiao_jian) 按维度统计条数
#   kou_kuan_tong_ji(...)        按维度统计扣款/扣分（从责任人字段解析）
#   zhao_lei_si(miao_shu, n)     按一段问题描述找相似历史案例
#   wei_du(ming)                 列出某维度的可选值及数量
#   xiang_qing(id)               单条考核详情
# ============================================

import datetime
import re
import time

from sqlalchemy import create_engine, text
import config

# 列表返回的字段（顺序即展示顺序）
_SHU_CHU_LIE = [
    "id", "信息单号", "状态", "检查时间", "录入时间", "落实时间", "销号时间",
    "年份", "月份", "级别", "问题层级", "问题来源", "问题分类",
    "检查人", "检查单位", "检查单位所在车间", "检查地点",
    "责任单位", "责任单位所在车间", "责任单位所在班组",
    "条例等级", "条例大类", "条例条目", "条例专业", "条例编码",
    "劳安问题", "十六种违章", "考核", "监管", "重要",
    "检查内容", "整改措施", "整改期限", "整改情况", "对规对标", "条例内容",
    "责任人1", "责任人2", "责任人3", "责任人4", "参与检查人",
]

# 关键词检索覆盖的正文列（多词时每个词都要命中其中至少一列）
_WEN_BEN_LIE = [
    "信息单号", "检查内容", "整改措施", "条例内容", "对规对标",
    "整改情况", "检查地点", "责任人1", "责任人2", "责任人3", "责任人4",
]

# 精确匹配的筛选项：参数名 -> 表字段
_DENG_YU = {
    "nian_fen": "年份",
    "yue_fen": "月份",
    "ji_bie": "级别",
    "wen_ti_ceng_ji": "问题层级",
    "tiao_li_da_lei": "条例大类",
    "tiao_li_zhuan_ye": "条例专业",
    "tiao_li_deng_ji": "条例等级",
    "zhuang_tai": "状态",
    "lao_an": "劳安问题",
    "shi_liu_zhong": "十六种违章",
    "wen_ti_lai_yuan": "问题来源",
    "wen_ti_fen_lei": "问题分类",
    "kao_he": "考核",
}

# 模糊匹配的筛选项（单位/班组/人名这类写全称容易漏，用包含即可）
_MO_HU = {
    "tiao_li_tiao_mu": "条例条目",
    "ze_ren_dan_wei": "责任单位",
    "ze_ren_che_jian": "责任单位所在车间",
    "ze_ren_ban_zu": "责任单位所在班组",
    "jian_cha_dan_wei": "检查单位",
    "jian_cha_che_jian": "检查单位所在车间",
    "jian_cha_ren": "检查人",
}

# 接口允许接收的筛选参数（其余参数一律忽略）
KE_SHAI_XUAN = tuple(_DENG_YU) + tuple(_MO_HU) + (
    "ze_ren_ren", "guan_jian_ci", "qi_shi", "jie_zhi", "zhong_dian")

# 允许分组的维度：展示名 -> SQL 表达式（只允许这里出现的字符串进入 SQL）
_FEN_ZU = {
    "年份": "[年份]",
    "月份": "[月份]",
    "年月": "CONVERT(varchar(7), [检查时间], 120)",
    "级别": "[级别]",
    "问题层级": "[问题层级]",
    "条例大类": "[条例大类]",
    "条例条目": "[条例条目]",
    "条例专业": "[条例专业]",
    "责任单位": "[责任单位]",
    "责任车间": "[责任单位所在车间]",
    "责任班组": "[责任单位所在班组]",
    "检查人": "[检查人]",
    "问题来源": "[问题来源]",
    "问题分类": "[问题分类]",
    "状态": "[状态]",
    "劳安问题": "[劳安问题]",
    "十六种违章": "[十六种违章]",
}

_YIN_QING = None          # 懒加载的只读引擎
_HUAN_CUN = {"shi_jian": 0.0, "hang": []}   # 全表缓存（相似案例用，5 分钟过期）


class KaoHeWeiPeiZhi(RuntimeError):
    """没有配置考核数据库时抛出，接口层转成友好提示。"""


def _yin_qing():
    """懒加载数据库引擎（第一次调用时建连接池）。"""
    global _YIN_QING
    if not getattr(config, "KAO_HE_KAI_QI", False):
        raise KaoHeWeiPeiZhi(
            "考核数据库未启用。请在首页「⚙️ 系统设置 → 考核数据库」里填写连接信息并启用。")
    if _YIN_QING is None:
        url = config.gou_jian_kao_he_lian_jie()
        if url is None:
            raise KaoHeWeiPeiZhi("考核数据库未配置连接信息。")
        _YIN_QING = create_engine(
            url, pool_pre_ping=True, pool_size=2, max_overflow=2, future=True)
    return _YIN_QING


def _biao() -> str:
    return f"[{config.KAO_HE_BIAO}]"


# ---------- 条件拼装 ----------

def _esc_like(zhi: str) -> str:
    """转义 LIKE 通配符，避免用户输入的 % _ [ 改变匹配含义。"""
    return zhi.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")


def _jie_xi_ri_qi(zhi: str):
    """解析日期，返回 (datetime, 粒度)。粒度：year/month/day/second。"""
    zhi = (zhi or "").strip().replace("/", "-").replace(".", "-")
    if not zhi:
        return None, None
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", zhi)
    if m:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))), "day"
    m = re.fullmatch(r"(\d{4})", zhi)
    if m:
        return datetime.datetime(int(m.group(1)), 1, 1), "year"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", zhi)
    if m:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), 1), "month"
    for fmt, li in (("%Y-%m-%d %H:%M:%S", "second"),
                    ("%Y-%m-%d %H:%M", "second"),
                    ("%Y-%m-%d", "day")):
        try:
            return datetime.datetime.strptime(zhi, fmt), li
        except ValueError:
            continue
    return None, None


def _ri_qi_fan_wei(qi_shi, jie_zhi):
    """把起止日期转成左闭右开的区间参数。"""
    tiao_jian, can_shu = [], {}
    kai, _ = _jie_xi_ri_qi(qi_shi)
    if kai:
        tiao_jian.append("[检查时间] >= :qi_shi")
        can_shu["qi_shi"] = kai
    mo, li = _jie_xi_ri_qi(jie_zhi)
    if mo:
        if li == "year":
            mo = mo.replace(year=mo.year + 1)
            tiao_jian.append("[检查时间] < :jie_zhi")
        elif li == "month":
            mo = (mo.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            tiao_jian.append("[检查时间] < :jie_zhi")
        elif li == "day":
            mo = mo + datetime.timedelta(days=1)
            tiao_jian.append("[检查时间] < :jie_zhi")
        else:
            tiao_jian.append("[检查时间] <= :jie_zhi")
        can_shu["jie_zhi"] = mo
    return tiao_jian, can_shu


def _gou_jian_tiao_jian(can_shu: dict):
    """把筛选参数转成 WHERE 子句片段和绑定变量。can_shu 为 None 时只返回空。"""
    can_shu = can_shu or {}
    tiao_jian, can_shu_zhong = [], {}

    for jian, lie in _DENG_YU.items():
        zhi = str(can_shu.get(jian) or "").strip()
        if zhi:
            tiao_jian.append(f"[{lie}] = :{jian}")
            can_shu_zhong[jian] = zhi

    for jian, lie in _MO_HU.items():
        zhi = str(can_shu.get(jian) or "").strip()
        if zhi:
            tiao_jian.append(f"[{lie}] LIKE :{jian}")
            can_shu_zhong[jian] = f"%{_esc_like(zhi)}%"

    ze_ren = str(can_shu.get("ze_ren_ren") or "").strip()
    if ze_ren:
        bu = " OR ".join(f"[责任人{i}] LIKE :ze_ren_ren" for i in range(1, 5))
        tiao_jian.append(f"({bu})")
        can_shu_zhong["ze_ren_ren"] = f"%{_esc_like(ze_ren)}%"

    if can_shu.get("zhong_dian"):
        tiao_jian.append("([重要] IS NOT NULL AND [重要] <> '')")

    guan_jian_ci = str(can_shu.get("guan_jian_ci") or "").strip()
    if guan_jian_ci:
        # 每个词都要命中（跨列 OR），词之间 AND；最多取前 10 个词，防止 SQL 过长
        for i, ci in enumerate(guan_jian_ci.split()[:10]):
            bu = " OR ".join(f"[{lie}] LIKE :kw{i}" for lie in _WEN_BEN_LIE)
            tiao_jian.append(f"({bu})")
            can_shu_zhong[f"kw{i}"] = f"%{_esc_like(ci)}%"

    ri_qi_tiao, ri_qi_can = _ri_qi_fan_wei(can_shu.get("qi_shi"), can_shu.get("jie_zhi"))
    tiao_jian.extend(ri_qi_tiao)
    can_shu_zhong.update(ri_qi_can)

    return tiao_jian, can_shu_zhong


def _where(tiao_jian):
    return (" WHERE " + " AND ".join(tiao_jian)) if tiao_jian else ""


# ---------- 结果转换 ----------

def _zhuan_zhi(v):
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return v


def _jie_xi_ze_ren(wen: str) -> dict:
    """解析"姓名：X，工作证号：Y，扣款：70.00，扣分：0.20"这类文本。"""
    d = {}
    for duan in re.split(r"[，,；;]", wen or ""):
        duan = duan.strip()
        if not duan:
            continue
        m = re.match(r"^([^：:]{1,12})[：:](.*)$", duan)
        if m:
            d[m.group(1).strip()] = m.group(2).strip()
    for k in ("扣款", "扣分"):
        if k in d:
            try:
                d[k] = float(re.sub(r"[^\d.\-]", "", d[k]) or 0)
            except ValueError:
                d[k] = 0.0
    return d


def _hang_zhuan_dict(hang) -> dict:
    d = {lie: _zhuan_zhi(hang._mapping.get(lie)) for lie in _SHU_CHU_LIE}
    ming_xi = []
    for i in range(1, 5):
        wen = d.get(f"责任人{i}") or ""
        if wen:
            ming_xi.append(_jie_xi_ze_ren(wen))
    d["责任人明细"] = ming_xi
    d["扣款合计"] = round(sum(x.get("扣款", 0) or 0 for x in ming_xi), 2)
    d["扣分合计"] = round(sum(x.get("扣分", 0) or 0 for x in ming_xi), 2)
    return d


# ---------- 对外查询 ----------

def cha_xun(**tiao_jian) -> dict:
    """按条件查询考核记录。

    常用参数（都可省略）：
      guan_jian_ci      关键词，空格分隔多个词（跨检查内容/整改措施/条例内容等）
      nian_fen/yue_fen  年份、月份（字符串，如 "2026"、"3"）
      qi_shi/jie_zhi    检查时间范围，支持 2025-03-01 / 2025-03 / 2025 / 20250301
      ji_bie            级别（车间级/站段级/路局级）
      wen_ti_ceng_ji    问题层级（现场/管理）
      tiao_li_da_lei    条例大类（设备质量/现场三违/安全管理/教育培训/其它问题）
      tiao_li_zhuan_ye  条例专业（车辆/公共/...）
      tiao_li_tiao_mu   条例条目（模糊）
      ze_ren_dan_wei / ze_ren_che_jian / ze_ren_ban_zu / ze_ren_ren
      jian_cha_dan_wei / jian_cha_ren / zhuang_tai / lao_an / shi_liu_zhong
      wen_ti_lai_yuan / wen_ti_fen_lei / kao_he / zhong_dian
      shu_liang        返回条数（默认20，最多200）
      pian_yi          偏移（分页）
      pai_xu           "asc" 按时间升序，默认降序
    """
    shu_liang = max(1, min(int(tiao_jian.pop("shu_liang", 20) or 20), 200))
    pian_yi = max(0, int(tiao_jian.pop("pian_yi", 0) or 0))
    pai_xu = "ASC" if str(tiao_jian.pop("pai_xu", "")).lower() in ("asc", "升序") else "DESC"

    where_bu, can_shu = _gou_jian_tiao_jian(tiao_jian)
    where_sql = _where(where_bu)
    lie_sql = ", ".join(f"[{lie}]" for lie in _SHU_CHU_LIE)
    sql = (f"SELECT {lie_sql} FROM {_biao()}{where_sql} "
           f"ORDER BY [检查时间] {pai_xu}, [id] {pai_xu} "
           f"OFFSET :pian_yi ROWS FETCH NEXT :shu_liang ROWS ONLY")
    can_shu.update({"pian_yi": pian_yi, "shu_liang": shu_liang})

    with _yin_qing().connect() as cn:
        hang_lie = cn.execute(text(sql), can_shu).fetchall()
        zong_shu = cn.execute(
            text(f"SELECT COUNT(*) FROM {_biao()}{where_sql}"),
            {k: v for k, v in can_shu.items() if k not in ("pian_yi", "shu_liang")}
        ).scalar_one()

    return {"zong_shu": int(zong_shu),
            "jie_guo": [_hang_zhuan_dict(h) for h in hang_lie]}


def tong_ji(fen_zu: str = "条例大类", **tiao_jian) -> dict:
    """按维度统计条数。fen_zu 见 _FEN_ZU；返回 [{zhi, shu}]，按数量倒序。"""
    biao_da_shi = _FEN_ZU.get(fen_zu)
    if not biao_da_shi:
        return {"cuo_wu": f"不支持的分组字段：{fen_zu}",
                "ke_xuan": list(_FEN_ZU.keys()), "jie_guo": []}

    where_bu, can_shu = _gou_jian_tiao_jian(tiao_jian)
    where_sql = _where(where_bu)
    # 月份/年月按值升序，其它按数量倒序
    pai_xu = f"{biao_da_shi} ASC" if fen_zu in ("月份", "年月") else "shu DESC"
    sql = (f"SELECT {biao_da_shi} AS zhi, COUNT(*) AS shu FROM {_biao()}{where_sql} "
           f"GROUP BY {biao_da_shi} ORDER BY {pai_xu}")

    with _yin_qing().connect() as cn:
        hang_lie = cn.execute(text(sql), can_shu).fetchall()

    return {"fen_zu": fen_zu,
            "jie_guo": [{"zhi": _zhuan_zhi(h.zhi), "shu": int(h.shu)} for h in hang_lie[:200]]}


def kou_kuan_tong_ji(fen_zu: str = "年月", **tiao_jian) -> dict:
    """按维度统计考核扣款/扣分（金额从责任人字段解析），按扣款倒序。"""
    if fen_zu not in ("年月", "年份", "月份", "责任单位", "责任车间", "责任班组", "检查人", "条例大类"):
        return {"cuo_wu": f"不支持的分组字段：{fen_zu}", "jie_guo": []}

    where_bu, can_shu = _gou_jian_tiao_jian(tiao_jian)
    where_sql = _where(where_bu)
    lie = {
        "年月": "CONVERT(varchar(7), [检查时间], 120)",
        "年份": "[年份]",
        "月份": "[月份]",
        "责任单位": "[责任单位]",
        "责任车间": "[责任单位所在车间]",
        "责任班组": "[责任单位所在班组]",
        "检查人": "[检查人]",
        "条例大类": "[条例大类]",
    }[fen_zu]
    sql = (f"SELECT {lie} AS zu, [责任人1], [责任人2], [责任人3], [责任人4] "
           f"FROM {_biao()}{where_sql}")

    ji = {}
    with _yin_qing().connect() as cn:
        for h in cn.execute(text(sql), can_shu):
            kou_kuan = kou_fen = 0.0
            for i in range(1, 5):
                wen = _zhuan_zhi(h._mapping.get(f"责任人{i}"))
                if wen:
                    d = _jie_xi_ze_ren(wen)
                    kou_kuan += d.get("扣款", 0) or 0
                    kou_fen += d.get("扣分", 0) or 0
            zhi = _zhuan_zhi(h.zu)
            x = ji.setdefault(zhi, {"zhi": zhi, "shu": 0, "kou_kuan": 0.0, "kou_fen": 0.0})
            x["shu"] += 1
            x["kou_kuan"] += kou_kuan
            x["kou_fen"] += kou_fen

    jie_guo = sorted(ji.values(), key=lambda x: x["kou_kuan"], reverse=True)
    for x in jie_guo:
        x["kou_kuan"] = round(x["kou_kuan"], 2)
        x["kou_fen"] = round(x["kou_fen"], 2)
    return {"fen_zu": fen_zu, "jie_guo": jie_guo[:200]}


def wei_du(ming: str = "") -> dict:
    """列出一个或多个维度的可选值及数量。不传 ming 时返回常用维度（每个最多30项）。"""
    chang_yong = ["年份", "月份", "级别", "问题层级", "条例大类", "条例专业",
                  "责任车间", "责任班组", "问题来源", "状态"]
    mu_biao = [ming] if ming in _FEN_ZU else chang_yong
    jie_guo = {}
    with _yin_qing().connect() as cn:
        for m in mu_biao:
            biao_da_shi = _FEN_ZU[m]
            pai_xu = f"{biao_da_shi} ASC" if m in ("月份", "年月") else "shu DESC"
            sql = (f"SELECT {biao_da_shi} AS zhi, COUNT(*) AS shu FROM {_biao()} "
                   f"GROUP BY {biao_da_shi} ORDER BY {pai_xu}")
            hang_lie = cn.execute(text(sql)).fetchall()
            jie_guo[m] = [{"zhi": _zhuan_zhi(h.zhi), "shu": int(h.shu)} for h in hang_lie[:50]]
    return {"wei_du": jie_guo}


def xiang_qing(ji_lu_id: int) -> dict:
    """单条考核详情（含解析后的责任人明细）。"""
    lie_sql = ", ".join(f"[{lie}]" for lie in _SHU_CHU_LIE)
    with _yin_qing().connect() as cn:
        hang = cn.execute(text(f"SELECT {lie_sql} FROM {_biao()} WHERE [id] = :id"),
                          {"id": int(ji_lu_id)}).first()
    return {"jie_guo": _hang_zhuan_dict(hang) if hang else None}


def _qu_quan_bu() -> list:
    """全表读取并缓存（相似案例检索用，5 分钟过期）。"""
    if _HUAN_CUN["hang"] and time.time() - _HUAN_CUN["shi_jian"] < 300:
        return _HUAN_CUN["hang"]
    lie_sql = ", ".join(f"[{lie}]" for lie in _SHU_CHU_LIE)
    with _yin_qing().connect() as cn:
        hang_lie = cn.execute(
            text(f"SELECT {lie_sql} FROM {_biao()} ORDER BY [检查时间] DESC")).fetchall()
    _HUAN_CUN["hang"] = [_hang_zhuan_dict(h) for h in hang_lie]
    _HUAN_CUN["shi_jian"] = time.time()
    return _HUAN_CUN["hang"]


def _zi_bigram(wen: str) -> set:
    """中文按二字组合切分，用来做轻量相似度（不依赖向量模型）。"""
    wen = re.sub(r"[^\w\u4e00-\u9fff]+", "", (wen or "").lower())
    return {wen[i:i + 2] for i in range(len(wen) - 1)} if len(wen) > 1 else {wen}


def zhao_lei_si(miao_shu: str, n: int = 10) -> dict:
    """给一段问题描述，找历史上最相似的考核案例（用于参考写分析/通报）。"""
    n = max(1, min(int(n or 10), 50))
    q = _zi_bigram(miao_shu)
    if not q:
        return {"jie_guo": [], "ti_shi": "描述太短"}

    jie_guo = []
    for hang in _qu_quan_bu():
        wen = " ".join(str(hang.get(k) or "") for k in
                       ("检查内容", "条例内容", "整改措施", "对规对标", "责任人1", "责任人2"))
        d = _zi_bigram(wen)
        if not d:
            continue
        xiang_tong = len(q & d)
        if not xiang_tong:
            continue
        fen = xiang_tong / len(q)                      # 查询覆盖度
        if str(hang.get("条例大类")) and str(hang.get("条例大类")) in miao_shu:
            fen += 0.15
        hang = dict(hang)
        hang["相似度"] = round(min(fen, 1.0), 3)
        jie_guo.append(hang)

    jie_guo.sort(key=lambda x: (-x["相似度"], x.get("检查时间", "")), reverse=False)
    return {"jie_guo": jie_guo[:n]}
