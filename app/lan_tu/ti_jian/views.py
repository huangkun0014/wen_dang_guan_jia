# -*- coding: utf-8 -*-
# ============================================
# 体检蓝图：既有文档的归类审核
# 路由前缀: /api/ti_jian
#   kai_shi  — 启动后台体检（选范围：全库/某分类）
#   jin_du   — 体检进度
#   jie_guo  — 体检结果列表（可按处理状态/建议动作过滤）
#   chu_li   — 批量执行：移动到建议分类 / 加为其他归口 / 忽略
# ============================================

import os
from flask import Blueprint, request, jsonify
import config
from app.moxing import Session, TiJianJieGuo
from app.gong_ju import ti_jian_fu_wu

ti_jian_bp = Blueprint("ti_jian", __name__, url_prefix="/api/ti_jian")


@ti_jian_bp.post("/kai_shi")
def kai_shi():
    """启动体检。body: {fan_wei: "" 全库 | "2025" 年份目录 | ...,
    zhui_jia: true 追加(默认) | false 全量重扫}"""
    body = request.get_json(force=True) or {}
    fan_wei = str(body.get("fan_wei", "")).strip().strip("/\\").replace("\\", "/")
    zhui_jia = bool(body.get("zhui_jia", True))
    yi_qi_dong = ti_jian_fu_wu.hou_tai_ti_jian(fan_wei, zhui_jia)
    return jsonify({"ok": yi_qi_dong,
                    "xin_xi": "已启动" if yi_qi_dong else "已有体检在运行"})


@ti_jian_bp.get("/jin_du")
def jin_du():
    return jsonify(ti_jian_fu_wu.jin_du)


@ti_jian_bp.get("/fan_wei_qing_dan")
def fan_wei_qing_dan():
    """体检范围清单：文档库里的年份目录（给前端下拉用）"""
    import re
    try:
        mu_lu = sorted(d for d in os.listdir(config.WEN_DANG_KU)
                       if re.fullmatch(r"20\d\d", d))
    except OSError:
        mu_lu = []
    return jsonify(mu_lu)


@ti_jian_bp.get("/jie_guo")
def jie_guo():
    """体检结果。参数：zhuang_tai=待审/已改标签/已加标签/已忽略/已重命名/已失效/全部，dong_zuo=gai_biao_qian/jia_biao_qian/bu_dong/全部"""
    zhuang_tai = request.args.get("zhuang_tai", "待审")
    dong_zuo = request.args.get("dong_zuo", "全部")
    db = Session()
    q = db.query(TiJianJieGuo)
    if zhuang_tai != "全部":
        q = q.filter_by(chu_li_zhuang_tai=zhuang_tai)
    if dong_zuo != "全部":
        q = q.filter_by(dong_zuo=dong_zuo)
    rows = q.order_by(TiJianJieGuo.id).limit(2000).all()
    # 待审条目：磁盘上文件已被删除/移走/改名 → 自动标记已失效，避免幽灵条目
    shi_xiao = 0
    if zhuang_tai == "待审":
        for r in rows:
            abs_p = os.path.join(config.WEN_DANG_KU, r.lu_jing)
            if not os.path.isfile(abs_p) or os.path.basename(abs_p) != r.wen_jian_ming:
                r.chu_li_zhuang_tai = "已失效"
                shi_xiao += 1
        if shi_xiao:
            db.commit()
            rows = [r for r in rows if r.chu_li_zhuang_tai == "待审"]
    jie_guo = [{
        "id": r.id,
        "lu_jing": r.lu_jing,
        "wen_jian_ming": r.wen_jian_ming,
        "dang_qian_biao_qian": r.dang_qian_biao_qian,
        "pan_duan": r.pan_duan,
        "jian_yi_biao_qian": r.jian_yi_biao_qian,
        "dong_zuo": r.dong_zuo,
        "li_you": r.li_you,
        "ming_wen_ti": r.ming_wen_ti,
        "gui_fan_ming": r.gui_fan_ming,
        "chu_li_zhuang_tai": r.chu_li_zhuang_tai,
    } for r in rows]
    # 各状态统计（给前端显示角标）
    tong_ji = {}
    for r in db.query(TiJianJieGuo).all():
        tong_ji[r.chu_li_zhuang_tai] = tong_ji.get(r.chu_li_zhuang_tai, 0) + 1
    db.close()
    return jsonify({"jie_guo": jie_guo, "tong_ji": tong_ji})


@ti_jian_bp.post("/chu_li")
def chu_li():
    """批量执行。body: {dong_zuo: "gai_biao_qian"|"jia_biao_qian"|"zhong_ming"|"ignore", ids: [1,2,3]}"""
    body = request.get_json(force=True) or {}
    dong_zuo = str(body.get("dong_zuo", ""))
    ids = [int(x) for x in (body.get("ids") or [])]
    if dong_zuo not in ("gai_biao_qian", "jia_biao_qian", "zhong_ming", "ignore") or not ids:
        return jsonify({"ok": False, "cuo_wu": "参数不对"}), 400
    return jsonify(ti_jian_fu_wu.chu_li_ti_jian(dong_zuo, ids))
