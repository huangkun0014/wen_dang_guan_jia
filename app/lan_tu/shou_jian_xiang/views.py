# -*- coding: utf-8 -*-
# ============================================
# 收件箱蓝图：待归档文件列表 / AI命名建议 / 执行归档
# 路由前缀: /api/shou_jian_xiang
# ============================================

import os
import re
import datetime
import threading
import time
from flask import Blueprint, request, jsonify
import config
from app.moxing import Session, GuiDangJiLu, WenJian
from app.gong_ju import (wen_jian_ti_qu, ming_ming_gui_ze, deepseek_api,
                         tupian_shibie, xiang_liang_ku, wen_jian_cao_zuo)

shou_jian_xiang_bp = Blueprint("shou_jian_xiang", __name__, url_prefix="/api/shou_jian_xiang")


def _nian_fen_cong_ming(wen_jian_ming: str, abs_p: str) -> str:
    """归档年份：从规范文件名的 8 位日期取，没有则取文件修改时间。与迁移规则一致。"""
    m = re.search(r"(20\d{6})", os.path.splitext(wen_jian_ming)[0])
    if m:
        return m.group(1)[:4]
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(abs_p)).strftime("%Y")
    except OSError:
        return datetime.datetime.now().strftime("%Y")

# 批量 AI 命名的进度状态（内存态，前端轮询读取；结果逐个落进 jie_guo）
pi_liang_jin_du = {
    "yun_xing_zhong": False,     # 是否有批量任务在跑
    "zong_shu": 0,               # 本次要处理的文件总数
    "wan_cheng": 0,              # 已完成数
    "zui_hou_xin_xi": "",        # 当前正在分析的文件名
    "jie_guo": {},               # path -> 建议字典（与单文件 jian_yi 接口同款）
}


@shou_jian_xiang_bp.get("/lie_biao")
def lie_biao():
    """收件箱当前文件列表"""
    os.makedirs(config.SHOU_JIAN_XIANG, exist_ok=True)
    jie_guo = []
    for f in sorted(os.listdir(config.SHOU_JIAN_XIANG)):
        abs_p = os.path.join(config.SHOU_JIAN_XIANG, f)
        if not os.path.isfile(abs_p):
            continue
        st = os.stat(abs_p)
        jie_guo.append({
            "ming": f,
            "abs_lu_jing": abs_p,
            "da_xiao": st.st_size,
            "ri_qi": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
        })
    return jsonify(jie_guo)


@shou_jian_xiang_bp.get("/jian_yi")
def jian_yi():
    """对单个文件给出归档建议。返回同 _jian_yi_yi_ge。"""
    abs_p = request.args.get("path", "")
    try:
        return jsonify(_jian_yi_yi_ge(abs_p))
    except ValueError as e:
        return jsonify({"ok": False, "cuo_wu": str(e)}), 400


def _jian_yi_yi_ge(abs_p):
    """单个文件的归档建议（提取内容 -> 图片识别 -> DeepSeek）。

    流程: 提取文本(或图片识别) -> DeepSeek生成 规范文件名+摘要+标签
          -> DeepSeek不可用时回退到规则命名
    返回: {ok, shi_yong_ai, wen_jian_ming, nian_fen, zhai_yao, biao_qian,
           nei_rong_yu_lan, tu_pian_shi_bai}
    文件不在收件箱时抛 ValueError。
    """
    if not _zai_shou_jian_xiang_li(abs_p):
        raise ValueError("文件不在收件箱")
    ming = os.path.basename(abs_p)

    # 1. 能提文本就提文本；不能提且是图片且开了本地识别，就识别图片
    kuo_zhan_ming = os.path.splitext(ming)[1].lower()
    tu_pian_kuo_zhan = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    shi_tu_pian = kuo_zhan_ming in tu_pian_kuo_zhan
    nei_rong = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, yun_xu_com=True)
    tu_pian_miao_shu = ""
    if not nei_rong and shi_tu_pian:
        tu_pian_miao_shu = tupian_shibie.shi_bie_tu_pian(abs_p)
        nei_rong = tu_pian_miao_shu
    # 图片没认出内容：记下原因，前端要提醒用户（而不是静默给个烂名字）
    tu_pian_shi_bai = ""
    if shi_tu_pian and not nei_rong:
        tu_pian_shi_bai = tupian_shibie.shang_ci_shi_bai_yuan_yin or "未能识别图片内容"

    # 2. AI 归档建议
    jie_guo = deepseek_api.zhi_neng_gui_dang(ming, nei_rong)
    if jie_guo:
        # 统一规范文件名（AI 可能只给 202610 这种不完整日期，这里补齐）
        jie_guo["wen_jian_ming"] = ming_ming_gui_ze.gui_fan_hua_ming(
            abs_p, jie_guo.get("wen_jian_ming", ming))
        return {
            "ok": True, "shi_yong_ai": True,
            "wen_jian_ming": jie_guo["wen_jian_ming"],
            "nian_fen": _nian_fen_cong_ming(jie_guo["wen_jian_ming"], abs_p),
            "zhai_yao": jie_guo.get("zhai_yao", ""),
            "biao_qian": jie_guo.get("biao_qian", ""),
            "nei_rong_yu_lan": (nei_rong or tu_pian_miao_shu)[:300],
            # 图片识别失败时前端必须提示用户：此时名字不是按图片内容起的
            "tu_pian_shi_bai": tu_pian_shi_bai,
        }

    # 3. 回退：规则命名 + 默认分类
    gui_ze_ming = ming_ming_gui_ze.ri_qi_qian_zhui(abs_p, ming)
    if not ming_ming_gui_ze.wen_jian_ming_you_yu_yi(gui_ze_ming) and nei_rong:
        # 文件名无语义时，从内容首行抓主题
        di_yi_hang = next(
            (l.strip() for l in nei_rong.split("\n")
             if 5 <= len(l.strip()) <= 40 and any("\u4e00" <= c <= "\u9fff" for c in l)),
            "")
        if di_yi_hang:
            import re
            zhu_ti = re.sub(r'[\\/:*?"<>|]', "", di_yi_hang)[:25]
            kzm = os.path.splitext(gui_ze_ming)[1]
            ri_qi = gui_ze_ming.split("_")[0]
            gui_ze_ming = f"{ri_qi}_{zhu_ti}{kzm}"
    return {
        "ok": True, "shi_yong_ai": False,
        "wen_jian_ming": gui_ze_ming,
        "nian_fen": _nian_fen_cong_ming(gui_ze_ming, abs_p),
        "zhai_yao": "", "biao_qian": "",
        "nei_rong_yu_lan": (nei_rong or tu_pian_miao_shu)[:300],
        "tu_pian_shi_bai": tu_pian_shi_bai,
    }


@shou_jian_xiang_bp.post("/pi_liang_jian_yi")
def pi_liang_jian_yi():
    """批量 AI 命名：body {paths: [绝对路径, ...]}。后台线程逐个分析，
    前端轮询 /pi_liang_jin_du 看进度并取回结果。"""
    body = request.get_json(force=True) or {}
    lu_jing = [str(p) for p in (body.get("paths") or [])]
    # 只处理此刻仍在收件箱里的文件
    lu_jing = [p for p in lu_jing if _zai_shou_jian_xiang_li(p)]
    if not lu_jing:
        return jsonify({"ok": False, "cuo_wu": "没有可处理的文件"}), 400
    if pi_liang_jin_du["yun_xing_zhong"]:
        return jsonify({"ok": False, "cuo_wu": "已有批量命名任务在跑"}), 400
    pi_liang_jin_du.update(yun_xing_zhong=True, zong_shu=len(lu_jing), wan_cheng=0,
                           jie_guo={}, zui_hou_xin_xi="排队中…")
    threading.Thread(target=_pi_liang_pao, args=(lu_jing,), daemon=True).start()
    return jsonify({"ok": True, "zong_shu": len(lu_jing)})


@shou_jian_xiang_bp.get("/pi_liang_jin_du")
def pi_liang_jin_du_jie_kou():
    """批量命名进度 + 已完成的建议结果"""
    return jsonify(pi_liang_jin_du)


def _pi_liang_pao(lu_jing):
    """批量命名后台任务：逐个分析，结果实时落进 pi_liang_jin_du['jie_guo']"""
    for i, p in enumerate(lu_jing, 1):
        pi_liang_jin_du["zui_hou_xin_xi"] = f"[{i}/{len(lu_jing)}] {os.path.basename(p)}"
        try:
            pi_liang_jin_du["jie_guo"][p] = _jian_yi_yi_ge(p)
        except Exception as e:
            pi_liang_jin_du["jie_guo"][p] = {"ok": False, "cuo_wu": str(e)}
        pi_liang_jin_du["wan_cheng"] = i
        time.sleep(0.3)      # 控制 API 请求频率，不顶到限速
    pi_liang_jin_du["yun_xing_zhong"] = False
    pi_liang_jin_du["zui_hou_xin_xi"] = "完成"


@shou_jian_xiang_bp.post("/gui_dang")
def gui_dang():
    """执行归档（单个）。body: {path, wen_jian_ming, zhai_yao, biao_qian}"""
    body = request.get_json(force=True) or {}
    ok, jie_guo = _gui_dang_yi_ge(
        str(body.get("path", "")), str(body.get("wen_jian_ming", "")).strip(),
        str(body.get("zhai_yao", "")), str(body.get("biao_qian", "")))
    return jsonify(jie_guo), (200 if ok else 400)


def _gui_dang_yi_ge(abs_p, xin_ming, zhai_yao="", biao_qian="", jian_suo_yin=True):
    """归档单个文件：移动到年份目录 + 记日志 + 更新索引 + 后台建向量。
    jian_suo_yin=False 时不单独起后台索引（全量重建会统一建）。
    返回 (是否成功, 结果字典)。"""
    if not _zai_shou_jian_xiang_li(abs_p) or not xin_ming:
        return False, {"ok": False, "cuo_wu": "参数不对"}
    # 文件名安全处理
    xin_ming = re.sub(r'[\\/:*?"<>|\r\n]+', "", xin_ming)
    # 归档目标 = 年份目录（年份从规范文件名里的 8 位日期取，与迁移规则一致）
    nian_fen = _nian_fen_cong_ming(xin_ming, abs_p)
    mu_lu = os.path.join(config.WEN_DANG_KU, nian_fen)
    os.makedirs(mu_lu, exist_ok=True)
    mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(mu_lu, xin_ming)
    # 带重试的移动：文件被 WPS/杀毒/索引器短暂占用时自动等待重试
    ok_yi_dong, cuo_wu = wen_jian_cao_zuo.yi_dong(abs_p, mu_biao)
    if not ok_yi_dong:
        return False, {"ok": False, "cuo_wu": str(cuo_wu)}

    xin_rel = os.path.relpath(mu_biao, config.WEN_DANG_KU)
    # 记归档日志
    db = Session()
    db.add(GuiDangJiLu(yuan_lu_jing=abs_p, xin_lu_jing=mu_biao))
    # 更新文件索引：删旧向量、把新文件加进索引
    xiang_liang_ku.shan_chu_wen_dang(os.path.basename(abs_p))
    ji_lu = db.query(WenJian).filter_by(wen_jian_ming=os.path.basename(abs_p)).first()
    if ji_lu:
        db.delete(ji_lu)
    db.add(WenJian(
        lu_jing=xin_rel, wen_jian_ming=os.path.basename(mu_biao),
        fen_lei=nian_fen, zhai_yao=zhai_yao, biao_qian=biao_qian,
        you_xiang_liang=0, wen_jian_mtime=""))
    db.commit()
    db.close()
    # 后台给新文件建向量（不等它，归档动作先返回；全量重建时会跳过这一步）
    if jian_suo_yin:
        threading.Thread(
            target=lambda: __import__("app.gong_ju.suo_yin_fu_wu", fromlist=["wen_jian_suo_yin"])
                .wen_jian_suo_yin((xin_rel, mu_biao)), daemon=True).start()

    return True, {"ok": True, "xin_lu_jing": mu_biao}


@shou_jian_xiang_bp.post("/pi_liang_gui_dang")
def pi_liang_gui_dang():
    """批量归档。body: {items: [{path, wen_jian_ming, zhai_yao, biao_qian}, ...]}
    逐个归档（图片/大文件移动很快，同步执行），返回每条成败。"""
    body = request.get_json(force=True) or {}
    items = body.get("items") or []
    if not items:
        return jsonify({"ok": False, "cuo_wu": "参数不对"}), 400
    cheng_gong, shi_bai = 0, []
    for it in items:
        ok, jie_guo = _gui_dang_yi_ge(
            str(it.get("path", "")), str(it.get("wen_jian_ming", "")).strip(),
            str(it.get("zhai_yao", "")), str(it.get("biao_qian", "")))
        if ok:
            cheng_gong += 1
        else:
            shi_bai.append(f"{os.path.basename(str(it.get('path', '')))}（{jie_guo.get('cuo_wu', '')}）")
    return jsonify({"ok": True, "cheng_gong": cheng_gong, "shi_bai": shi_bai})


@shou_jian_xiang_bp.get("/biao_qian_ci_hui")
def biao_qian_ci_hui():
    """标签参考词库（给前端 datalist 用，供用户补/改标签时参考）"""
    return jsonify(deepseek_api.BIAO_QIAN_CI_HUI)


def _zai_shou_jian_xiang_li(abs_p: str) -> bool:
    """安全检查：路径必须真实存在于收件箱内"""
    if not abs_p:
        return False
    return (os.path.abspath(abs_p).startswith(os.path.abspath(config.SHOU_JIAN_XIANG))
            and os.path.isfile(abs_p))
