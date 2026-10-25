# -*- coding: utf-8 -*-
# ============================================
# 浏览蓝图：像资源管理器一样层级浏览文档库
# 路由前缀: /api/liu_lan
#
# 提供三个能力：
#   1. mu_lu    — 列出某目录下的子文件夹和文件（面包屑导航）
#   2. shen_he  — 重命名前的命名规范审核（只检查，不改文件）
#   3. zhong_ming — 执行重命名：改名 + 清旧向量/旧台账 + 后台重建新向量
#
# 命名规范（与收件箱归档同一套标准）：
#   YYYYMMDD_主题.扩展名；日期取文件名里的，没有就补文件修改日期；
#   去掉非法字符和 OA 下载尾缀；扩展名不允许改。
# ============================================

import os
import datetime
from flask import Blueprint, request, jsonify
import config
from app.moxing import Session, WenJian, GuiDangJiLu
from app.gong_ju import (xiang_liang_ku, ming_ming_gui_ze, wen_jian_ti_qu,
                         deepseek_api, tupian_shibie, wen_jian_cao_zuo)

liu_lan_bp = Blueprint("liu_lan", __name__, url_prefix="/api/liu_lan")

# 批量 AI 处理（命名+标签+摘要）的进度状态（内存态，前端轮询读取）
pi_liang_fen_xi_jin_du = {
    "yun_xing_zhong": False,
    "zong_shu": 0,
    "wan_cheng": 0,
    "zui_hou_xin_xi": "",
    "jie_guo": {},   # path -> {ok, ming, yuan_ming, zhai_yao, biao_qian, shi_yong_ai, tu_pian_shi_bai, nei_rong_yu_lan}
}

# Windows 文件名非法字符（和系统一致）
FEI_FA_ZI_FU = '\\/:*?"<>|'


def _an_quan_lu_jing(rel: str):
    """把前端传来的相对路径解析成绝对路径，并校验不越出文档库。
    返回 (ok, abs_path 或 None, error_msg)。"""
    base = os.path.abspath(config.WEN_DANG_KU)
    rel = (rel or "").strip().strip("/\\")
    target = os.path.abspath(os.path.join(base, rel)) if rel else base
    if not (target == base or target.startswith(base + os.sep)):
        return False, None, "路径越出文档库"
    return True, target, ""


@liu_lan_bp.get("/mu_lu")
def mu_lu():
    """列出目录内容。参数 path=相对路径（空表示根目录）。"""
    ok, target, err = _an_quan_lu_jing(request.args.get("path", ""))
    if not ok:
        return jsonify({"ok": False, "cuo_wu": err}), 403
    if not os.path.isdir(target):
        return jsonify({"ok": False, "cuo_wu": "目录不存在"}), 404

    rel = os.path.relpath(target, os.path.abspath(config.WEN_DANG_KU))
    xiang_dui = "" if rel == "." else rel.replace(os.sep, "/")

    wen_jian_jia, wen_jian = [], []
    for ming in sorted(os.listdir(target)):
        if ming == "文件索引总表.xlsx":
            continue
        abs_p = os.path.join(target, ming)
        if os.path.isdir(abs_p):
            wen_jian_jia.append(ming)
        elif os.path.isfile(abs_p):
            st = os.stat(abs_p)
            wen_jian.append({
                "ming": ming,
                "abs_lu_jing": abs_p,
                "da_xiao": st.st_size,
                "ri_qi": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                "kuo_zhan_ming": os.path.splitext(ming)[1].lower(),
            })

    # 摘要/标签批量补上（新模型下标签是分类载体，浏览时直接可见；一次查询不分条查）
    if wen_jian:
        db = Session()
        try:
            qian = (xiang_dui.replace("/", os.sep) + os.sep) if xiang_dui else ""
            xin_xi = {}
            for hang in db.query(WenJian).filter(WenJian.lu_jing.like(qian + "%")).all():
                xin_xi[os.path.basename(hang.lu_jing.replace("/", os.sep))] = \
                    (hang.zhai_yao or "", hang.biao_qian or "")
        finally:
            db.close()
        for f in wen_jian:
            zhai, biao = xin_xi.get(f["ming"], ("", ""))
            f["zhai_yao"] = zhai
            f["biao_qian"] = biao

    # 面包屑：根目录 -> 一级 -> 二级 ...
    mian_bao = [{"ming": "文档库", "path": ""}]
    if xiang_dui:
        lei_ji = ""
        for duan in xiang_dui.split("/"):
            lei_ji = f"{lei_ji}/{duan}" if lei_ji else duan
            mian_bao.append({"ming": duan, "path": lei_ji})

    return jsonify({
        "ok": True,
        "dang_qian": xiang_dui,
        "mian_bao": mian_bao,
        "wen_jian_jia": wen_jian_jia,
        "wen_jian": wen_jian,
    })


def _shen_he(xin_ming: str, yuan_ming: str, abs_p: str):
    """命名规范审核：返回 (规范后的文件名, 审核意见列表)。"""
    yi_jian = []
    kuo_zhan_ming = os.path.splitext(yuan_ming)[1]          # 扩展名始终以原文件为准

    # 1. 非法字符
    qing_xi = xin_ming
    for c in FEI_FA_ZI_FU:
        qing_xi = qing_xi.replace(c, "")
    if qing_xi != xin_ming.strip():
        yi_jian.append("已去掉文件名中的非法字符（\\/:*?\"<>|）")

    # 2. 扩展名保护：用户改了或删了扩展名都强制还原
    zhu_ti, kzm = os.path.splitext(qing_xi.strip())
    if not zhu_ti.strip():
        return None, ["文件名不能为空"]
    if kzm.lower() != kuo_zhan_ming.lower():
        yi_jian.append(f"扩展名已还原为原文件的 {kuo_zhan_ming}")

    # 3. 套命名规则清洗（去OA尾缀）+ 补日期前缀
    if zhu_ti.strip().startswith(("微信图片_", "mmexport")):
        yi_jian.append("微信图片编号是身份标识，未做剥离")
    gui_fan = ming_ming_gui_ze.ri_qi_qian_zhui(abs_p, zhu_ti.strip() + kuo_zhan_ming)
    import re as _re
    if not _re.match(r"^20\d{6}_", os.path.splitext(qing_xi.strip())[0]):
        yi_jian.append("原名称没有日期前缀，已按规则补上（取文件名或修改日期）")

    # 4. 语义检查
    if not ming_ming_gui_ze.wen_jian_ming_you_yu_yi(gui_fan):
        yi_jian.append("主题语义不明确，建议点\"AI 规范命名\"生成一个达意的名字")

    # 5. 年份归属提醒：新名字的年份和所在年份目录不一致时提醒（只提醒，不自动移动文件）
    nian_m = _re.search(r"(20\d{6})", os.path.splitext(gui_fan)[0])
    if nian_m:
        nian = nian_m.group(1)[:4]
        suo_zai = os.path.basename(os.path.dirname(abs_p))
        if _re.fullmatch(r"20\d\d", suo_zai) and suo_zai != nian:
            yi_jian.append(f"注意：新名字的年份是 {nian}，与所在目录 {suo_zai} 不一致，"
                           f"文件会留在原目录（想挪到对应年份目录请删除后用收件箱重新归档）")

    return gui_fan, yi_jian


@liu_lan_bp.get("/shen_he")
def shen_he_jie_kou():
    """重命名审核（预览，不改文件）。参数: path=文件绝对路径, xin_ming=用户输入的新名"""
    abs_p = request.args.get("path", "")
    xin_ming = request.args.get("xin_ming", "")
    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    gui_fan, yi_jian = _shen_he(xin_ming, os.path.basename(abs_p), abs_p)
    if gui_fan is None:
        return jsonify({"ok": False, "cuo_wu": "；".join(yi_jian)}), 400
    # 同名检查（同目录已存在且不是自身）
    if os.path.exists(os.path.join(os.path.dirname(abs_p), gui_fan)) and gui_fan != os.path.basename(abs_p):
        yi_jian.append(f"注意：同目录已存在 {gui_fan}，确认后将自动追加序号")
    return jsonify({"ok": True, "gui_fan_ming": gui_fan, "yi_jian": yi_jian})


@liu_lan_bp.get("/ai_ming")
def ai_ming():
    """AI 规范命名建议（浏览页重命名用）。参数: path=文件绝对路径"""
    abs_p = request.args.get("path", "")
    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    return jsonify(_ai_ming_yi_ge(abs_p))


def _ai_ming_yi_ge(abs_p):
    """单个文件的 AI 规范命名（内容与收件箱归档同一套流程）：
    能提文本就提文本；提不出且是图片，走视觉模型识别（通道见 config）；再交 DeepSeek 起名。"""
    yuan_ming = os.path.basename(abs_p)
    kuo_zhan_ming = os.path.splitext(yuan_ming)[1].lower()
    tu_pian_kuo_zhan = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    shi_tu_pian = kuo_zhan_ming in tu_pian_kuo_zhan
    nei_rong = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, yun_xu_com=True)
    if not nei_rong and shi_tu_pian:
        nei_rong = tupian_shibie.shi_bie_tu_pian(abs_p)
    # 图片没认出内容时告诉前端，名字仅供参考（与收件箱同一行为）
    tu_pian_shi_bai = ""
    if shi_tu_pian and not nei_rong:
        tu_pian_shi_bai = tupian_shibie.shang_ci_shi_bai_yuan_yin or "未能识别图片内容"
    suo_zai = os.path.dirname(os.path.relpath(abs_p, config.WEN_DANG_KU))
    # 优先 DeepSeek；失败回退规则命名
    ming = deepseek_api.gui_fan_ming_jian_yi(yuan_ming, nei_rong, suo_zai)
    shi_yong_ai = ming is not None
    if not ming:
        ming = ming_ming_gui_ze.ri_qi_qian_zhui(abs_p, yuan_ming)
    # 再过一遍本地审核，保证落库的名字一定规范
    gui_fan, yi_jian = _shen_he(ming, yuan_ming, abs_p)
    if gui_fan:
        ming = gui_fan
    return {"ok": True, "ming": ming, "shi_yong_ai": shi_yong_ai,
            "yi_jian": yi_jian, "nei_rong_yu_lan": (nei_rong or "")[:200],
            "tu_pian_shi_bai": tu_pian_shi_bai}


@liu_lan_bp.post("/biao_qian")
def geng_xin_biao_qian():
    """手动改标签/摘要。body: {path: 文件绝对路径, biao_qian, zhai_yao}
    更新台账 + 后台重建向量（标签在向量文本里，必须重嵌）。"""
    body = request.get_json(force=True) or {}
    abs_p = str(body.get("path", ""))
    biao_qian = str(body.get("biao_qian", ""))[:500]
    zhai_yao = str(body.get("zhai_yao", ""))[:500]
    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    rel = os.path.relpath(abs_p, config.WEN_DANG_KU)
    db = Session()
    try:
        ji_lu = db.query(WenJian).filter_by(lu_jing=rel).first()
        if ji_lu is None:
            ji_lu = WenJian(lu_jing=rel, wen_jian_ming=os.path.basename(abs_p),
                            fen_lei=os.path.dirname(rel))
            db.add(ji_lu)
        ji_lu.biao_qian = biao_qian
        ji_lu.zhai_yao = zhai_yao
        ji_lu.you_xiang_liang = 0
        db.commit()
    finally:
        db.close()
    import threading
    threading.Thread(
        target=lambda: __import__("app.gong_ju.suo_yin_fu_wu", fromlist=["wen_jian_suo_yin"])
            .wen_jian_suo_yin((rel, abs_p)), daemon=True).start()
    return jsonify({"ok": True})


@liu_lan_bp.get("/biao_qian_ai")
def biao_qian_ai():
    """AI 给单个文件生成标签+摘要建议（图片走视觉识别，其余走文本提取）。
    只返回建议不落库，用户确认后由 /biao_qian 保存。"""
    abs_p = request.args.get("path", "")
    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    ming = os.path.basename(abs_p)
    kuo_zhan_ming = os.path.splitext(ming)[1].lower()
    nei_rong = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, zi_shu_shang_xian=2000, yun_xu_com=True)
    if not nei_rong and kuo_zhan_ming in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"):
        nei_rong = tupian_shibie.shi_bie_tu_pian(abs_p, yong_tu="jie_xi")
    if not nei_rong:
        return jsonify({"ok": False,
                        "cuo_wu": "提不出内容（老格式/扫描件），AI 无法生成，请手动填写"}), 400
    jie_guo = deepseek_api.sheng_cheng_zhai_yao(ming, nei_rong)
    if not jie_guo:
        return jsonify({"ok": False, "cuo_wu": "DeepSeek 调用失败，请稍后重试"}), 502
    return jsonify({"ok": True,
                    "zhai_yao": jie_guo.get("zhai_yao", ""),
                    "biao_qian": jie_guo.get("biao_qian", ""),
                    "nei_rong_yu_lan": nei_rong[:300]})


@liu_lan_bp.post("/pi_liang_fen_xi")
def pi_liang_fen_xi():
    """批量 AI 处理（第一步：分析）。body {paths: [绝对路径, ...]}
    后台逐个生成 规范名+摘要+标签，前端轮询 /pi_liang_fen_xi_jin_du 取回，
    人工审阅修改后再调 /pi_liang_chu_li 应用。"""
    body = request.get_json(force=True) or {}
    gen = os.path.abspath(config.WEN_DANG_KU)
    lu_jing = []
    for p in (body.get("paths") or []):
        p = str(p)
        # 只处理文档库内的真实文件
        if os.path.isfile(p) and os.path.abspath(p).startswith(gen):
            lu_jing.append(p)
    if not lu_jing:
        return jsonify({"ok": False, "cuo_wu": "没有可处理的文件"}), 400
    if pi_liang_fen_xi_jin_du["yun_xing_zhong"]:
        return jsonify({"ok": False, "cuo_wu": "已有批量任务在跑"}), 400
    pi_liang_fen_xi_jin_du.update(yun_xing_zhong=True, zong_shu=len(lu_jing), wan_cheng=0,
                                  jie_guo={}, zui_hou_xin_xi="排队中…")
    import threading
    threading.Thread(target=_pi_liang_fen_xi_pao, args=(lu_jing,), daemon=True).start()
    return jsonify({"ok": True, "zong_shu": len(lu_jing)})


@liu_lan_bp.get("/pi_liang_fen_xi_jin_du")
def pi_liang_fen_xi_jin_du_jie_kou():
    """批量 AI 处理进度 + 已完成的分析结果"""
    return jsonify(pi_liang_fen_xi_jin_du)


def _pi_liang_fen_xi_pao(lu_jing):
    """批量分析后台任务：逐个分析，结果实时落进进度字典"""
    import time
    for i, p in enumerate(lu_jing, 1):
        pi_liang_fen_xi_jin_du["zui_hou_xin_xi"] = f"[{i}/{len(lu_jing)}] {os.path.basename(p)}"
        try:
            pi_liang_fen_xi_jin_du["jie_guo"][p] = _fen_xi_yi_ge(p)
        except Exception as e:
            pi_liang_fen_xi_jin_du["jie_guo"][p] = {"ok": False, "cuo_wu": str(e)}
        pi_liang_fen_xi_jin_du["wan_cheng"] = i
        time.sleep(0.3)      # 控制 API 请求频率，不顶到限速
    pi_liang_fen_xi_jin_du["yun_xing_zhong"] = False
    pi_liang_fen_xi_jin_du["zui_hou_xin_xi"] = "完成"


def _fen_xi_yi_ge(abs_p):
    """批量处理用：AI 一次生成 规范名+摘要+标签。
    .doc/.xls 老格式走 COM 提取；图片走视觉识别；AI 失败回退规则命名。"""
    yuan_ming = os.path.basename(abs_p)
    kuo_zhan_ming = os.path.splitext(yuan_ming)[1].lower()
    tu_pian_kuo_zhan = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
    shi_tu_pian = kuo_zhan_ming in tu_pian_kuo_zhan
    nei_rong = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, zi_shu_shang_xian=2000, yun_xu_com=True)
    if not nei_rong and shi_tu_pian:
        nei_rong = tupian_shibie.shi_bie_tu_pian(abs_p, yong_tu="jie_xi")
    tu_pian_shi_bai = ""
    if shi_tu_pian and not nei_rong:
        tu_pian_shi_bai = tupian_shibie.shang_ci_shi_bai_yuan_yin or "未能识别图片内容"
    # 统一走归档建议那套提示词：一次调用出 文件名+摘要+标签
    jie_guo = deepseek_api.zhi_neng_gui_dang(yuan_ming, nei_rong)
    if jie_guo:
        xin_ming = jie_guo["wen_jian_ming"]
        zhai_yao = jie_guo.get("zhai_yao", "")
        biao_qian = jie_guo.get("biao_qian", "")
        shi_yong_ai = True
    else:
        xin_ming = ming_ming_gui_ze.ri_qi_qian_zhui(abs_p, yuan_ming)
        zhai_yao = biao_qian = ""
        shi_yong_ai = False
    # 再过一遍本地审核，保证给出的名字规范（不通过就维持原名）
    gui_fan, _yi_jian = _shen_he(xin_ming, yuan_ming, abs_p)
    xin_ming = gui_fan or yuan_ming
    return {"ok": True, "ming": xin_ming, "yuan_ming": yuan_ming,
            "zhai_yao": zhai_yao, "biao_qian": biao_qian, "shi_yong_ai": shi_yong_ai,
            "tu_pian_shi_bai": tu_pian_shi_bai,
            "nei_rong_yu_lan": (nei_rong or "")[:200]}


@liu_lan_bp.post("/pi_liang_chu_li")
def pi_liang_chu_li():
    """批量 AI 处理（第二步：应用）。body {items: [{path, xin_ming?, biao_qian?, zhai_yao?}, ...]}
    每条：改名（可选）+ 更新标签/摘要（可选）一次完成，最后统一重建向量。
    字段缺省（None）= 该项不修改；前端三种模式按需拼字段：
    改名+标签 / 只改标签 / 只改文件名。"""
    body = request.get_json(force=True) or {}
    items = body.get("items") or []
    if not items or len(items) > 500:
        return jsonify({"ok": False, "cuo_wu": "参数不对（一次 1~500 条）"}), 400
    cheng_gong, shi_bai = 0, []
    chong_jian_ren_wu = []
    for it in items:
        try:
            ok, xin_xi, ren_wu = _chu_li_yi_ge(it)
        except Exception as e:
            ok, xin_xi, ren_wu = False, str(e), None
        if ok:
            cheng_gong += 1
            if ren_wu:
                chong_jian_ren_wu.append(ren_wu)
        else:
            shi_bai.append(f"{os.path.basename(str(it.get('path', '')))}（{xin_xi}）")
    # 向量重建：单线程顺序跑（批量大时避免开一堆线程抢着加载模型）
    if chong_jian_ren_wu:
        import threading

        def _chong_jian_pao(ren_wu_lie):
            suo_yin = __import__("app.gong_ju.suo_yin_fu_wu", fromlist=["wen_jian_suo_yin"])
            for rel, abs_p in ren_wu_lie:
                try:
                    suo_yin.wen_jian_suo_yin((rel, abs_p))
                except Exception:
                    pass

        threading.Thread(target=_chong_jian_pao, args=(chong_jian_ren_wu,), daemon=True).start()
    return jsonify({"ok": True, "cheng_gong": cheng_gong, "shi_bai": shi_bai})


def _chu_li_yi_ge(item: dict):
    """批量处理单条：改名（可选）+ 更新标签/摘要（可选），台账同步。
    返回 (是否成功, 错误说明, 向量重建任务 (rel, abs) 或 None)。"""
    abs_p = str(item.get("path", ""))
    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return False, "文件不存在或不在文档库", None
    yuan_ming = os.path.basename(abs_p)
    yuan_abs = abs_p
    old_rel = os.path.relpath(abs_p, config.WEN_DANG_KU)

    # ---- 改名（可选，走和单文件重命名同一套审核规范） ----
    gai_ming = False
    xin_ming = item.get("xin_ming")
    if xin_ming is not None and str(xin_ming).strip():
        gui_fan, _yi_jian = _shen_he(str(xin_ming).strip(), yuan_ming, abs_p)
        if gui_fan and gui_fan != yuan_ming:
            mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(os.path.dirname(abs_p), gui_fan)
            ok_gm, cuo_wu = wen_jian_cao_zuo.gai_ming(abs_p, mu_biao)
            if not ok_gm:
                return False, f"重命名失败：{cuo_wu}", None
            abs_p = mu_biao
            gai_ming = True

    new_rel = os.path.relpath(abs_p, config.WEN_DANG_KU)

    # ---- 台账更新（标签/摘要只在给了值时改；改名必须改路径） ----
    db = Session()
    try:
        ji_lu = db.query(WenJian).filter(
            (WenJian.lu_jing == old_rel) | (WenJian.lu_jing == old_rel.replace(os.sep, "/"))).first()
        if gai_ming:
            mu_biao_hang = db.query(WenJian).filter(
                (WenJian.lu_jing == new_rel) | (WenJian.lu_jing == new_rel.replace(os.sep, "/"))).first()
            if mu_biao_hang is not None and mu_biao_hang is not ji_lu:
                db.delete(mu_biao_hang)      # 目标路径有残留旧记录，清掉避免唯一键冲突
            db.add(GuiDangJiLu(yuan_lu_jing=yuan_abs, xin_lu_jing=abs_p))
        if ji_lu is None:
            ji_lu = WenJian(lu_jing=new_rel, wen_jian_ming=os.path.basename(abs_p),
                            fen_lei=os.path.dirname(new_rel))
            db.add(ji_lu)
        elif gai_ming:
            ji_lu.lu_jing = new_rel
            ji_lu.wen_jian_ming = os.path.basename(abs_p)
            ji_lu.fen_lei = os.path.dirname(new_rel)
        if item.get("biao_qian") is not None:
            ji_lu.biao_qian = str(item.get("biao_qian"))[:500]
        if item.get("zhai_yao") is not None:
            ji_lu.zhai_yao = str(item.get("zhai_yao"))[:500]
        ji_lu.you_xiang_liang = 0
        db.commit()
    finally:
        db.close()

    if gai_ming:
        try:
            xiang_liang_ku.shan_chu_wen_dang(old_rel)
        except Exception:
            pass
    return True, "", (new_rel, abs_p)


@liu_lan_bp.post("/zhong_ming")
def zhong_ming():
    """执行重命名。body: {path: 文件绝对路径, xin_ming: 新文件名（会先过审核规范）}"""
    body = request.get_json(force=True) or {}
    abs_p = str(body.get("path", ""))
    xin_ming = str(body.get("xin_ming", ""))

    if not os.path.isfile(abs_p) or not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return jsonify({"ok": False, "cuo_wu": "文件不存在或不在文档库"}), 404
    yuan_ming = os.path.basename(abs_p)

    # 审核 + 规范（服务端再兜一遍，前端显示什么就存什么标准）
    gui_fan, yi_jian = _shen_he(xin_ming, yuan_ming, abs_p)
    if gui_fan is None:
        return jsonify({"ok": False, "cuo_wu": "；".join(yi_jian)}), 400

    mu_lu = os.path.dirname(abs_p)
    # 规范后和原名一样 = 名字没变，直接返回（不能走 bi_kai_chong_ming，否则会把文件自己当重名追加 _2）
    if gui_fan == yuan_ming:
        return jsonify({"ok": True, "xin_ming": yuan_ming, "xin_xi": "名字没有变化", "yi_jian": yi_jian})
    mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(mu_lu, gui_fan)

    ok_gm, cuo_wu = wen_jian_cao_zuo.gai_ming(abs_p, mu_biao)
    if not ok_gm:
        return jsonify({"ok": False, "cuo_wu": f"重命名失败：{cuo_wu}"}), 500

    # 索引联动：删旧向量、改台账路径（保留摘要/标签，改名只是换路径，元数据不能丢），后台重建新向量
    old_rel = os.path.relpath(abs_p, config.WEN_DANG_KU)
    new_rel = os.path.relpath(mu_biao, config.WEN_DANG_KU)
    try:
        xiang_liang_ku.shan_chu_wen_dang(old_rel)
    except Exception:
        pass
    db = Session()
    try:
        ji_lu = db.query(WenJian).filter(
            (WenJian.lu_jing == old_rel) | (WenJian.lu_jing == old_rel.replace(os.sep, "/"))).first()
        mu_biao_hang = db.query(WenJian).filter(
            (WenJian.lu_jing == new_rel) | (WenJian.lu_jing == new_rel.replace(os.sep, "/"))).first()
        if mu_biao_hang is not None and mu_biao_hang is not ji_lu:
            db.delete(mu_biao_hang)           # 目标路径有残留旧记录，清掉避免唯一键冲突
        if ji_lu is not None:
            ji_lu.lu_jing = new_rel
            ji_lu.wen_jian_ming = os.path.basename(mu_biao)
            ji_lu.fen_lei = os.path.dirname(new_rel)
            ji_lu.you_xiang_liang = 0         # 位置变了，向量必须重建（标签/摘要原样保留）
        # 没记录的（从没进过索引）交给后台重建时建档
        db.add(GuiDangJiLu(yuan_lu_jing=abs_p, xin_lu_jing=mu_biao))
        db.commit()
    finally:
        db.close()
    import threading
    threading.Thread(
        target=lambda: __import__("app.gong_ju.suo_yin_fu_wu", fromlist=["wen_jian_suo_yin"])
            .wen_jian_suo_yin((new_rel, mu_biao)), daemon=True).start()

    return jsonify({"ok": True, "xin_ming": os.path.basename(mu_biao),
                    "xin_lu_jing": mu_biao, "yi_jian": yi_jian,
                    "zhui": os.path.basename(mu_biao) != gui_fan})
