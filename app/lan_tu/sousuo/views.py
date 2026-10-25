# -*- coding: utf-8 -*-
# ============================================
# 搜索蓝图：文件名搜索 + 语义搜索
# 路由前缀: /api/sousuo
# ============================================

import os
import subprocess
import sys
from flask import Blueprint, request, jsonify
import config

sousuo_bp = Blueprint("sousuo", __name__, url_prefix="/api/sousuo")


def _sao_miao():
    """实时遍历文档库（文件名搜索不走数据库，保证新文件立刻能搜到）"""
    jie_guo = []
    for dp, ds, fs in os.walk(config.WEN_DANG_KU):
        ds[:] = [d for d in ds if not d.startswith("99-") and d != "00-收件箱"]
        for f in fs:
            if f.startswith("~$") or f == "文件索引总表.xlsx":
                continue
            abs_p = os.path.join(dp, f)
            jie_guo.append({
                "ming": f,
                "abs_lu_jing": abs_p,
                "xiang_dui_lu_jing": os.path.relpath(abs_p, config.WEN_DANG_KU),
            })
    return jie_guo


@sousuo_bp.get("/ming_cheng")
def sou_ming_cheng():
    """按文件名/路径/标签搜索。多个关键词空格分隔，全部命中才算。
    结果带摘要和标签（新模型下标签是分类载体，文件名搜索也该能看见）。"""
    from app.moxing import Session, WenJian
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify([])
    tiao_jian = q.split()

    wen_zhong = (request.args.get("wen_zhong") or "").strip()
    nian_fen = (request.args.get("nian_fen") or "").strip()

    # 先把台账全部取出来（1400 行左右，一次查询）：标签也参与关键词匹配，
    # 这样搜"消防"能命中文件名没有"消防"、但打了消防标签的文件
    db = Session()
    try:
        xin_xi = {}
        for ji_lu in db.query(WenJian).all():
            xin_xi[ji_lu.lu_jing.replace("\\", "/")] = (
                ji_lu.zhai_yao or "", ji_lu.biao_qian or "",
                ji_lu.wen_zhong or "", ji_lu.nian_fen or 0)
    finally:
        db.close()

    jie_guo = []
    for f in _sao_miao():
        zhai, biao, lei, nian = xin_xi.get(
            f["xiang_dui_lu_jing"].replace("\\", "/"), ("", "", "", 0))
        if wen_zhong and lei != wen_zhong:
            continue
        if nian_fen and str(nian) != nian_fen:
            continue
        mu_biao = (f["ming"] + " " + f["xiang_dui_lu_jing"] + " " + biao).lower()
        if all(t in mu_biao for t in tiao_jian):
            f["zhai_yao"] = zhai
            f["biao_qian"] = biao
            f["wen_zhong"] = lei
            f["nian_fen"] = nian
            jie_guo.append(f)
        if len(jie_guo) >= 200:
            break
    return jsonify(jie_guo)


@sousuo_bp.get("/yu_yi")
def sou_yu_yi():
    """按意思搜索（混合检索：分块语义 + 关键词 + 整篇语义）。
    返回文件级结果，带最佳"相关片段"和数据库里的摘要/标签。"""
    from app.gong_ju import sou_suo_fu_wu
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    nian = request.args.get("nian_fen") or ""
    return jsonify(sou_suo_fu_wu.hu_he_sou_suo(
        q, int(request.args.get("n", 20)),
        wen_zhong=(request.args.get("wen_zhong") or "").strip(),
        nian_fen=int(nian) if nian.isdigit() else None))


@sousuo_bp.post("/da_kai")
def da_kai():
    """打开文件或所在文件夹。body: {path, mode: 'file'|'folder'}

    path 支持绝对路径或相对文档库的路径（相对路径在服务端拼接，跨平台更稳）。
    """
    body = request.get_json(force=True) or {}
    mu_biao = str(body.get("path", "")).strip()
    gen = os.path.abspath(config.WEN_DANG_KU)
    if not os.path.isabs(mu_biao):
        mu_biao = os.path.join(gen, mu_biao)
    mu_biao = os.path.abspath(mu_biao)
    # 安全限制：只允许操作文档库内的路径（用 commonpath 避免 D:\文档库2 这种前缀绕过）
    try:
        if os.path.commonpath([gen, mu_biao]) != gen:
            return jsonify({"ok": False, "cuo_wu": "路径不在文档库内"}), 403
    except ValueError:
        return jsonify({"ok": False, "cuo_wu": "路径不在文档库内"}), 403
    if not os.path.exists(mu_biao):
        return jsonify({"ok": False, "cuo_wu": "文件或目录不存在"}), 404
    if body.get("mode") == "folder" and os.path.isfile(mu_biao):
        mu_biao = os.path.dirname(mu_biao)
    try:
        if os.name == "nt":
            os.startfile(mu_biao)          # Windows：文件/文件夹都能用默认程序打开
        elif sys.platform == "darwin":
            subprocess.Popen(["open", mu_biao])
        else:
            subprocess.Popen(["xdg-open", mu_biao])
    except Exception as e:
        return jsonify({"ok": False, "cuo_wu": f"打开失败：{e}"}), 500
    return jsonify({"ok": True})
