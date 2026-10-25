# -*- coding: utf-8 -*-
# ============================================
# AI 接入蓝图：给外部 AI 应用（MCP / 脚本 / 其他软件）查阅文档库的本机接口
# 路由前缀: /api/ai
#
#   GET /sousuo?q=&n=      混合检索（摘要/标签/相关片段）
#   GET /du?path=          读文档完整正文（最多2万字；.doc/.xls 走 WPS 提取）
#   GET /wen_jian?path=    单个文件元数据
#   GET /biao_qian         全部标签及数量（帮 AI 选检索词）
#   GET /jin_qi?days=&n=   最近更新的文件
#   GET /kao_he?...        考核台账查询（SQL Server，只读）
#   GET /kao_he/tong_ji?fen_zu=      按维度统计条数
#   GET /kao_he/kou_kuan?fen_zu=     按维度统计扣款/扣分
#   GET /kao_he/wei_du?ming=         维度可选值
#   GET /kao_he/lei_si?miao_shu=&n=  找相似历史考核案例
#   GET /kao_he/xiang_qing?id=       单条详情
#
# 鉴权：config.AI_JIE_KOU_KEY 非空时需请求头 X-API-Key；
# 服务本身只监听 127.0.0.1，默认空 key 时仅本机可用。
# ============================================

import os
import datetime
from flask import Blueprint, request, jsonify
import config
from app.moxing import Session, WenJian
from app.gong_ju import sou_suo_fu_wu, wen_jian_ti_qu, tupian_shibie, kao_he_shu_ju

ai_jie_kou_bp = Blueprint("ai_jie_kou", __name__, url_prefix="/api/ai")

# 图片扩展名（提不出文本时走视觉识别）
TU_PIAN_KZM = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


def _yan_zheng() -> bool:
    if not config.AI_JIE_KOU_KEY:
        return True
    return request.headers.get("X-API-Key", "") == config.AI_JIE_KOU_KEY


def _ju_jue():
    return jsonify({"ok": False, "cuo_wu": "API Key 不正确"}), 401


def _an_quan_lu_jing(rel_huo_jue: str):
    """接受相对/绝对路径，统一成 (rel, abs)；越出文档库返回 (None, None)。"""
    p = (rel_huo_jue or "").strip()
    if not p:
        return None, None
    if not os.path.isabs(p):
        p = os.path.join(config.WEN_DANG_KU, p.replace("/", os.sep))
    p = os.path.abspath(p)
    gen = os.path.abspath(config.WEN_DANG_KU)
    if not p.startswith(gen + os.sep):
        return None, None
    return os.path.relpath(p, gen), p


def _zhao_deng_ji(db, rel: str):
    """按相对路径查台账行（兼容正反斜杠两种历史写法）。"""
    return db.query(WenJian).filter(
        WenJian.lu_jing.in_({rel, rel.replace(os.sep, "/")})).first()


@ai_jie_kou_bp.get("/sousuo")
def ai_sousuo():
    """混合检索。参数 q=查询词，n=条数（默认10，最多50）"""
    if not _yan_zheng():
        return _ju_jue()
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "cuo_wu": "缺少 q 参数"}), 400
    n = int(request.args.get("n", 10) or 10)
    nian = (request.args.get("nian_fen") or "").strip()
    return jsonify({"ok": True, "q": q, "jie_guo": sou_suo_fu_wu.hu_he_sou_suo(
        q, n,
        wen_zhong=(request.args.get("wen_zhong") or "").strip(),
        nian_fen=int(nian) if nian.isdigit() else None)})


@ai_jie_kou_bp.get("/du")
def ai_du():
    """读文件完整正文（最多2万字）。path 支持相对路径或绝对路径。"""
    if not _yan_zheng():
        return _ju_jue()
    rel, abs_p = _an_quan_lu_jing(request.args.get("path", ""))
    if not rel or not os.path.isfile(abs_p):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    wen = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, zi_shu_shang_xian=20000, yun_xu_com=True)
    if not wen and os.path.splitext(abs_p)[1].lower() in TU_PIAN_KZM:
        wen = tupian_shibie.shi_bie_tu_pian(abs_p, yong_tu="jie_xi")
    db = Session()
    try:
        hang = _zhao_deng_ji(db, rel)
        zhai_yao = (hang.zhai_yao if hang else "") or ""
        biao_qian = (hang.biao_qian if hang else "") or ""
        wen_zhong = (hang.wen_zhong if hang else "") or ""
        nian_fen = (hang.nian_fen if hang else 0) or 0
    finally:
        db.close()
    return jsonify({"ok": True, "lu_jing": rel.replace(os.sep, "/"),
                    "wen_jian_ming": os.path.basename(abs_p),
                    "biao_qian": biao_qian, "zhai_yao": zhai_yao,
                    "wen_zhong": wen_zhong, "nian_fen": nian_fen,
                    "wen_ben": wen, "zi_shu": len(wen)})


@ai_jie_kou_bp.get("/wen_jian")
def ai_wen_jian():
    """单个文件元数据（标签、摘要、更新时间）。"""
    if not _yan_zheng():
        return _ju_jue()
    rel, abs_p = _an_quan_lu_jing(request.args.get("path", ""))
    if not rel or not os.path.isfile(abs_p):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    db = Session()
    try:
        hang = _zhao_deng_ji(db, rel)
        wen_jian = {
            "lu_jing": rel.replace(os.sep, "/"),
            "wen_jian_ming": os.path.basename(abs_p),
            "biao_qian": (hang.biao_qian if hang else "") or "",
            "zhai_yao": (hang.zhai_yao if hang else "") or "",
            "wen_zhong": (hang.wen_zhong if hang else "") or "",
            "nian_fen": (hang.nian_fen if hang else 0) or 0,
            "geng_xin_shi_jian": str(hang.geng_xin_shi_jian) if hang else "",
        }
    finally:
        db.close()
    return jsonify({"ok": True, "wen_jian": wen_jian})


@ai_jie_kou_bp.get("/biao_qian")
def ai_biao_qian():
    """全部标签及出现次数（帮 AI 了解库里有什么、用什么词检索），按数量倒序。"""
    if not _yan_zheng():
        return _ju_jue()
    from collections import Counter
    db = Session()
    try:
        ji = Counter()
        for hang in db.query(WenJian).all():
            for t in (hang.biao_qian or "").replace("，", ",").split(","):
                t = t.strip()
                if t:
                    ji[t] += 1
    finally:
        db.close()
    return jsonify({"ok": True,
                    "biao_qian": [{"biao_qian": k, "shu": v} for k, v in ji.most_common(200)]})


@ai_jie_kou_bp.get("/wen_zhong")
def ai_wen_zhong():
    """文种分布（让 AI 知道库里有哪些文种、各多少文件）。"""
    if not _yan_zheng():
        return _ju_jue()
    from app.gong_ju import wen_zhong_fu_wu
    return jsonify({"ok": True, **wen_zhong_fu_wu.tong_ji()})


@ai_jie_kou_bp.post("/chong_pai")
def ai_chong_pai():
    """条款重排：body {q, items:[{ming,tiao_kuan,pian_duan}]}，返回 0-based 顺序。"""
    if not _yan_zheng():
        return _ju_jue()
    body = request.get_json(force=True) or {}
    q = (body.get("q") or "").strip()
    items = body.get("items") or []
    if not q or not items:
        return jsonify({"ok": False, "cuo_wu": "缺少 q 或 items"}), 400
    from app.gong_ju import deepseek_api
    shun_xu = deepseek_api.chong_pai_tiao_kuan(q, items)
    return jsonify({"ok": True, "shun_xu": shun_xu})


@ai_jie_kou_bp.get("/jin_qi")
def ai_jin_qi():
    """最近 N 天（默认30）更新过的文件。"""
    if not _yan_zheng():
        return _ju_jue()
    days = max(1, int(request.args.get("days", 30) or 30))
    n = max(1, min(int(request.args.get("n", 20) or 20), 100))
    since = datetime.datetime.now() - datetime.timedelta(days=days)
    db = Session()
    try:
        hang_lie = (db.query(WenJian)
                    .filter(WenJian.geng_xin_shi_jian >= since)
                    .order_by(WenJian.geng_xin_shi_jian.desc()).limit(n).all())
        jie_guo = [{"lu_jing": h.lu_jing.replace(os.sep, "/"),
                    "wen_jian_ming": h.wen_jian_ming,
                    "biao_qian": h.biao_qian or "",
                    "zhai_yao": h.zhai_yao or "",
                    "geng_xin_shi_jian": str(h.geng_xin_shi_jian)} for h in hang_lie]
    finally:
        db.close()
    return jsonify({"ok": True, "jie_guo": jie_guo})


# ============================================
# 考核台账（SQL Server 只读）
# 参数名与 kao_he_shu_ju 模块一致，见该模块开头注释
# ============================================

def _kao_he_cuo_wu(e):
    """考核库未配置返回 400，其它错误返回 500。"""
    if isinstance(e, kao_he_shu_ju.KaoHeWeiPeiZhi):
        return jsonify({"ok": False, "cuo_wu": str(e)}), 400
    return jsonify({"ok": False, "cuo_wu": f"考核库查询失败：{e}"}), 500


def _kao_he_can_shu() -> dict:
    """从 query string 提取白名单筛选参数（zhong_dian 转布尔）。"""
    can_shu = {}
    for jian in kao_he_shu_ju.KE_SHAI_XUAN:
        zhi = (request.args.get(jian) or "").strip()
        if zhi:
            can_shu[jian] = zhi
    if can_shu.get("zhong_dian"):
        can_shu["zhong_dian"] = can_shu["zhong_dian"].lower() in ("1", "true", "是", "yes")
    return can_shu


@ai_jie_kou_bp.get("/kao_he")
def ai_kao_he():
    """按条件查考核记录。n=条数(默认20,最多200)，offset=偏移，sort=asc/desc。"""
    if not _yan_zheng():
        return _ju_jue()
    can_shu = _kao_he_can_shu()
    can_shu["shu_liang"] = request.args.get("n", 20)
    can_shu["pian_yi"] = request.args.get("offset", 0)
    can_shu["pai_xu"] = request.args.get("sort", "")
    try:
        r = kao_he_shu_ju.cha_xun(**can_shu)
    except Exception as e:
        return _kao_he_cuo_wu(e)
    return jsonify({"ok": True, **r})


@ai_jie_kou_bp.get("/kao_he/tong_ji")
def ai_kao_he_tong_ji():
    """按维度统计考核条数。fen_zu=条例大类（默认），支持年份/月份/年月/级别/责任班组等。"""
    if not _yan_zheng():
        return _ju_jue()
    fen_zu = (request.args.get("fen_zu") or "条例大类").strip()
    try:
        r = kao_he_shu_ju.tong_ji(fen_zu, **_kao_he_can_shu())
    except Exception as e:
        return _kao_he_cuo_wu(e)
    return jsonify({"ok": True, **r})


@ai_jie_kou_bp.get("/kao_he/kou_kuan")
def ai_kao_he_kou_kuan():
    """按维度统计扣款/扣分。fen_zu=年月（默认）/年份/月份/责任单位/责任车间/责任班组/检查人/条例大类。"""
    if not _yan_zheng():
        return _ju_jue()
    fen_zu = (request.args.get("fen_zu") or "年月").strip()
    try:
        r = kao_he_shu_ju.kou_kuan_tong_ji(fen_zu, **_kao_he_can_shu())
    except Exception as e:
        return _kao_he_cuo_wu(e)
    return jsonify({"ok": True, **r})


@ai_jie_kou_bp.get("/kao_he/wei_du")
def ai_kao_he_wei_du():
    """维度可选值及数量（让 AI 知道有哪些车间/班组/条例大类可筛）。"""
    if not _yan_zheng():
        return _ju_jue()
    try:
        r = kao_he_shu_ju.wei_du((request.args.get("ming") or "").strip())
    except Exception as e:
        return _kao_he_cuo_wu(e)
    return jsonify({"ok": True, **r})


@ai_jie_kou_bp.get("/kao_he/lei_si")
def ai_kao_he_lei_si():
    """给一段问题描述，找历史上相似的考核案例（参考写分析/通报）。"""
    if not _yan_zheng():
        return _ju_jue()
    miao_shu = (request.args.get("miao_shu") or "").strip()
    if not miao_shu:
        return jsonify({"ok": False, "cuo_wu": "缺少 miao_shu 参数"}), 400
    try:
        r = kao_he_shu_ju.zhao_lei_si(miao_shu, request.args.get("n", 10))
    except Exception as e:
        return _kao_he_cuo_wu(e)
    return jsonify({"ok": True, **r})


@ai_jie_kou_bp.get("/kao_he/xiang_qing")
def ai_kao_he_xiang_qing():
    """单条考核详情（含解析后的责任人/扣款明细）。"""
    if not _yan_zheng():
        return _ju_jue()
    try:
        r = kao_he_shu_ju.xiang_qing(int(request.args.get("id", 0)))
    except Exception as e:
        return _kao_he_cuo_wu(e)
    if not r.get("jie_guo"):
        return jsonify({"ok": False, "cuo_wu": "没有这条记录"}), 404
    return jsonify({"ok": True, **r})
