# -*- coding: utf-8 -*-
# ============================================
# 系统蓝图：运行状态总览 + 模型设置
# 路由前缀: /api/xi_tong
#   zhuang_tai      — 首页状态卡片（文件数/索引数/各部件连通性）
#   she_zhi         — 读取当前模型设置（GET）/ 保存并热生效（POST）
#   she_zhi_ce_shi  — 用当前生效的 key 探测 DeepSeek 是否可用
# ============================================

import os
import config
from flask import Blueprint, jsonify, request
from app.moxing import Session, WenJian
from app.gong_ju import suo_yin_fu_wu, she_zhi_fu_wu

xi_tong_bp = Blueprint("xi_tong", __name__, url_prefix="/api/xi_tong")


@xi_tong_bp.get("/zhuang_tai")
def zhuang_tai():
    """首页状态卡片用：文件总数、已索引数、向量数、各部件是否就绪"""
    # 实时文件数
    wen_jian_shu = len(suo_yin_fu_wu.sao_miao_lie_biao())
    # 数据库状态
    try:
        db = Session()
        yi_suo_yin = db.query(WenJian).filter_by(you_xiang_liang=1).count()
        you_zhai_yao = db.query(WenJian).filter(WenJian.zhai_yao != "").count()
        db.close()
        shu_ju_ku_ok = True
    except Exception:
        yi_suo_yin, you_zhai_yao, shu_ju_ku_ok = 0, 0, False
    # 向量库状态
    try:
        from app.gong_ju import xiang_liang_ku
        xiang_liang_shu = xiang_liang_ku.ku_zhong_zong_shu()
        fen_kuai_shu = xiang_liang_ku.fen_kuai_zong_shu()
    except Exception:
        xiang_liang_shu = 0
        fen_kuai_shu = 0
    # 图片识别通道连通性：按 config 的通道分别探测——
    # deepseek=查 DeepSeek 接口；lm_studio=查本地服务。不通时首页要能看出来
    tu_pian_shi_bie_qu_dao = getattr(config, "TU_PIAN_SHI_BIE_QU_DAO", "lm_studio")
    try:
        if tu_pian_shi_bie_qu_dao == "deepseek":
            from app.gong_ju import deepseek_api
            # 没配 Key 就别去请求接口，避免首页状态卡每次等 6 秒
            tu_pian_shi_bie_lian_tong = bool(config.DEEPSEEK_KEY) and \
                deepseek_api.jie_kou_lian_tong()
        else:
            from app.gong_ju import tupian_shibie
            tu_pian_shi_bie_lian_tong = (config.TU_PIAN_SHI_BIE_KAI_GUAN
                                         and tupian_shibie.lm_studio_zai_xian())
    except Exception:
        tu_pian_shi_bie_lian_tong = False
    return jsonify({
        "wen_jian_zong_shu": wen_jian_shu,
        "yi_suo_yin_shu": yi_suo_yin,
        "you_zhai_yao_shu": you_zhai_yao,
        "xiang_liang_shu": xiang_liang_shu,
        "fen_kuai_shu": fen_kuai_shu,
        "shu_ju_ku_ok": shu_ju_ku_ok,
        "tu_pian_shi_bie_kai_qi": config.TU_PIAN_SHI_BIE_KAI_GUAN,
        "tu_pian_shi_bie_qu_dao": tu_pian_shi_bie_qu_dao,
        "tu_pian_shi_bie_lian_tong": tu_pian_shi_bie_lian_tong,
        "wen_dang_ku": config.WEN_DANG_KU,
        "shou_jian_xiang": config.SHOU_JIAN_XIANG,
        "suo_yin_zhong": suo_yin_fu_wu.jin_du["yun_xing_zhong"],
    })


@xi_tong_bp.get("/she_zhi")
def she_zhi():
    """读取当前模型设置（key 打码返回，不回显完整密钥）"""
    return jsonify(she_zhi_fu_wu.du_qu_she_zhi())


@xi_tong_bp.post("/she_zhi")
def she_zhi_bao_cun():
    """保存设置并热生效。

    body 可包含：文档库路径、应用库/考核库连接、DeepSeek、MCP/端口、提示词。
    留空/缺省的项不修改；提示词传空串 = 恢复默认。
    """
    body = request.get_json(force=True) or {}
    ok, xin_xi, chong_qi, she = she_zhi_fu_wu.bao_cun_she_zhi(**body)
    jie_guo = {"ok": ok, "xin_xi": xin_xi, "xu_yao_chong_qi": chong_qi}
    jie_guo.update(she)
    return jsonify(jie_guo), (200 if ok else 400)


@xi_tong_bp.post("/db_ce_shi")
def db_ce_shi():
    """测试数据库连接。body: {lei_xing, sqlite_lu_jing, sql_server, sql_yong_hu,
    sql_mi_ma, sql_shu_ju_ku, biao, kao_he}"""
    body = request.get_json(force=True) or {}
    ok, xin_xi = she_zhi_fu_wu.ce_shi_shu_ju_ku(**body)
    return jsonify({"ok": ok, "xin_xi": xin_xi}), (200 if ok else 400)


@xi_tong_bp.get("/she_zhi_ce_shi")
def she_zhi_ce_shi():
    """用当前生效的 key 探测 DeepSeek 接口是否可用（列模型接口，不花 token）"""
    from app.gong_ju import deepseek_api
    lian_tong = deepseek_api.jie_kou_lian_tong()
    return jsonify({"ok": lian_tong,
                    "xin_xi": "连接正常" if lian_tong else "连不上（检查网络或 Key 是否有效）"})
