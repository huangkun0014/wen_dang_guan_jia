# -*- coding: utf-8 -*-
# ============================================
# 索引蓝图：触发索引、查看进度、重建索引、AI批量生成摘要标签
# 路由前缀: /api/suo_yin
# ============================================

from flask import Blueprint, jsonify, request
from app.gong_ju import suo_yin_fu_wu

suo_yin_bp = Blueprint("suo_yin", __name__, url_prefix="/api/suo_yin")


@suo_yin_bp.post("/kai_shi")
def kai_shi():
    """启动一轮增量索引（后台线程，前端轮询 /jin_du 看进度）"""
    yi_qi_dong = suo_yin_fu_wu.hou_tai_suo_yin()
    return jsonify({"ok": yi_qi_dong, "xin_xi": "已启动" if yi_qi_dong else "已有任务在运行"})


@suo_yin_bp.get("/jin_du")
def jin_du():
    """索引进度"""
    return jsonify(suo_yin_fu_wu.jin_du)


@suo_yin_bp.post("/chong_jian")
def chong_jian():
    """全量重建（后台线程）。body 可选：
    {chu_li_shou_jian_xiang: true 先处理收件箱（AI命名+归档）,
     ai_gui_fan_ming: true 用 AI 统一规范文件名}
    """
    body = request.get_json(silent=True) or {}
    yi_qi_dong = suo_yin_fu_wu.chong_jian_suo_yin(
        chu_li_shou_jian_xiang=bool(body.get("chu_li_shou_jian_xiang", False)),
        ai_ming=bool(body.get("ai_gui_fan_ming", False)))
    return jsonify({"ok": yi_qi_dong, "xin_xi": "已启动全量重建" if yi_qi_dong else "已有任务在运行"})


@suo_yin_bp.get("/jian_cha")
def jian_cha():
    """矢量库完整性检查：三方对账（磁盘文件 vs 数据库记录 vs 向量库条目）。

    四种典型情况：
      待索引   —— 磁盘有文件但数据库没记录（从没进过索引），点增量索引即可
      向量丢失 —— 数据库标记"已有向量"但向量库里实际没有（向量库损坏/被外部清过），
                 点"一键修复"程序会把标记复位再增量重建
      孤儿记录 —— 数据库有记录但磁盘文件没了（文件被外部删除），不影响搜索
      多余向量 —— 向量库有残留条目，全量重建可清掉
    新模型下所有文件都有向量（提取不出文字的文件也有"文件名+标签"的向量），
    wu_wen_ben_shu（无向量记录数）应保持 0。
    """
    import os
    from app.moxing import Session, WenJian
    from app.gong_ju import xiang_liang_ku

    # 磁盘上的真实文件（相对路径，统一用 / 分隔）
    ci_pan = {rel.replace(os.sep, "/") for rel, _ in suo_yin_fu_wu.sao_miao_lie_biao()}
    # 数据库记录
    db = Session()
    ji_lu_lie = db.query(WenJian).all()
    db.close()
    db_lu_jing = {j.lu_jing.replace("\\", "/") for j in ji_lu_lie}
    you_xiang_liang_lu = {j.lu_jing.replace("\\", "/") for j in ji_lu_lie if j.you_xiang_liang == 1}
    # 向量库全部 id
    try:
        xiang_liang_ids = {i.replace("\\", "/") for i in xiang_liang_ku.quan_bu_ids()}
    except Exception:
        xiang_liang_ids = set()

    que_suo_yin = sorted(ci_pan - db_lu_jing)                        # 磁盘有、库无记录
    xiang_liang_diu_shi = sorted(you_xiang_liang_lu - xiang_liang_ids)  # 库说有、向量无
    wu_wen_ben_shu = len(db_lu_jing - you_xiang_liang_lu)            # 正常无向量的文件数
    gu_er_ji_lu = sorted(db_lu_jing - ci_pan)                        # 库里有、磁盘没有
    duo_yu_xiang_liang = sorted(xiang_liang_ids - you_xiang_liang_lu)  # 向量残留
    return jsonify({
        "ci_pan_shu": len(ci_pan),
        "ji_lu_shu": len(db_lu_jing),
        "xiang_liang_shu": len(xiang_liang_ids),
        "you_xiang_liang_ji_lu_shu": len(you_xiang_liang_lu),
        "que_suo_yin": que_suo_yin[:200],
        "que_suo_yin_shu": len(que_suo_yin),
        "xiang_liang_diu_shi": xiang_liang_diu_shi[:200],
        "xiang_liang_diu_shi_shu": len(xiang_liang_diu_shi),
        "wu_wen_ben_shu": wu_wen_ben_shu,
        "gu_er_ji_lu": gu_er_ji_lu[:200],
        "gu_er_ji_lu_shu": len(gu_er_ji_lu),
        "duo_yu_xiang_liang": duo_yu_xiang_liang[:200],
        "duo_yu_xiang_liang_shu": len(duo_yu_xiang_liang),
    })


@suo_yin_bp.post("/xiu_fu")
def xiu_fu():
    """修复"向量丢失"：把丢失向量的文件在数据库里标记复位，再启动增量索引重建。

    只修这一类问题（标记复位后增量索引会按文件重建向量）。
    多余向量/孤儿记录不在这里动，多余向量请用全量重建清。
    """
    from app.moxing import Session, WenJian
    from app.gong_ju import xiang_liang_ku

    # 找出"标记有向量但向量库没有"的文件
    db = Session()
    ji_lu_lie = db.query(WenJian).filter_by(you_xiang_liang=1).all()
    try:
        xiang_liang_ids = {i.replace("\\", "/") for i in xiang_liang_ku.quan_bu_ids()}
    except Exception:
        xiang_liang_ids = set()
    diu_shi = [j for j in ji_lu_lie
               if j.lu_jing.replace("\\", "/") not in xiang_liang_ids]
    for j in diu_shi:
        j.you_xiang_liang = 0      # 复位标记，增量索引会重新给这些文件建向量
    db.commit()
    db.close()
    yi_qi_dong = suo_yin_fu_wu.hou_tai_suo_yin()
    return jsonify({"ok": True, "xiu_fu_shu": len(diu_shi),
                    "suo_yin_yi_qi_dong": yi_qi_dong,
                    "xin_xi": f"已复位 {len(diu_shi)} 条标记" + ("，并启动增量索引" if yi_qi_dong else "（索引任务已在运行）")})


@suo_yin_bp.post("/pi_liang_zhai_yao")
def pi_liang_zhai_yao():
    """给还没有摘要的文件批量调 DeepSeek 生成摘要和标签（后台跑）。

    这一步可选：摘要是锦上添花，不做也能搜索。摘要用于语义搜索结果页展示。
    """
    import threading
    threading.Thread(target=_pi_liang_sheng_cheng, daemon=True).start()
    return jsonify({"ok": True, "xin_xi": "后台生成中"})


def _pi_liang_sheng_cheng():
    """后台任务：遍历缺摘要的文件，逐个调DeepSeek。跑一轮就行，中断也无害。"""
    import os
    import time
    from app.moxing import Session, WenJian
    from app.gong_ju import deepseek_api, wen_jian_ti_qu
    import config
    db = Session()
    que = db.query(WenJian).filter(WenJian.zhai_yao == "").limit(300).all()
    db.close()
    for ji_lu in que:
        abs_p = os.path.join(config.WEN_DANG_KU, ji_lu.lu_jing)
        if not os.path.exists(abs_p):
            continue
        wen_ben = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, zi_shu_shang_xian=2000)
        if not wen_ben:
            continue
        jie_guo = deepseek_api.sheng_cheng_zhai_yao(ji_lu.wen_jian_ming, wen_ben)
        if jie_guo:
            db = Session()
            db.query(WenJian).filter_by(lu_jing=ji_lu.lu_jing).update({
                WenJian.zhai_yao: jie_guo.get("zhai_yao", "")[:200],
                WenJian.biao_qian: jie_guo.get("biao_qian", "")[:200],
            })
            db.commit()
            db.close()
        time.sleep(0.5)      # 控制请求频率，不顶到API限速
