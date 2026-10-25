# -*- coding: utf-8 -*-
# ============================================
# 文件管理蓝图：删除文档库里的文件
# 路由前缀: /api/wen_jian
#
# 删除策略（防误删设计）：
#   1. 不真正删除，而是移动到「文档库路径」下的 99-回收站（99- 开头的目录不参与索引和搜索）
#   2. 同步清掉矢量库里的旧向量
#   3. 同步删掉数据库里的文件台账记录
#   4. 记一条归档日志，可追溯
# 回收站里的文件确认没用了再手动清空。
# ============================================

import os
import shutil
import datetime
from flask import Blueprint, request, jsonify
import config
from app.moxing import Session, WenJian, GuiDangJiLu
from app.gong_ju import xiang_liang_ku

wen_jian_bp = Blueprint("wen_jian", __name__, url_prefix="/api/wen_jian")

# 回收站目录（和索引导扫的排除规则一致：99- 开头）
HUI_SHOU_ZHAN = os.path.join(config.WEN_DANG_KU, "99-回收站")


def yi_ge_shan_chu(abs_p: str, xu_hao: int = 0):
    """删除单个文件：移入回收站 + 清向量 + 清台账 + 记日志。
    返回 (True, 回收站文件名) 或 (False, 错误原因)。"""
    # 安全检查 1：必须真实存在于文档库内
    if not os.path.abspath(abs_p).startswith(os.path.abspath(config.WEN_DANG_KU)):
        return False, "路径不在文档库内"
    if not os.path.isfile(abs_p):
        return False, "文件不存在"
    # 安全检查 2：回收站里的文件不重复进回收站
    if os.path.abspath(abs_p).startswith(os.path.abspath(HUI_SHOU_ZHAN)):
        return False, "文件已在回收站"

    rel = os.path.relpath(abs_p, config.WEN_DANG_KU)

    # 1. 移入回收站（时间戳+序号前缀，批量同秒也不冲突）
    os.makedirs(HUI_SHOU_ZHAN, exist_ok=True)
    hui_shou_ming = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + f"{xu_hao:03d}_" + os.path.basename(abs_p)
    hui_shou_path = os.path.join(HUI_SHOU_ZHAN, hui_shou_ming)
    try:
        shutil.move(abs_p, hui_shou_path)
    except Exception as e:
        return False, f"移动失败：{e}"

    # 2. 清向量（向量 id 用的是文档库相对路径）
    try:
        xiang_liang_ku.shan_chu_wen_dang(rel)
    except Exception:
        pass     # 向量清理失败不阻断删除，之后全量重建也能兜底

    # 3. 清数据库台账 + 记日志
    db = Session()
    try:
        db.query(WenJian).filter_by(lu_jing=rel).delete()
        db.add(GuiDangJiLu(yuan_lu_jing=abs_p, xin_lu_jing=hui_shou_path))
        db.commit()
    except Exception as e:
        db.rollback()
        return False, f"数据库清理失败：{e}"
    finally:
        db.close()

    return True, hui_shou_ming


@wen_jian_bp.post("/shan_chu")
def shan_chu():
    """删除文件。body: {path: 绝对路径}"""
    body = request.get_json(force=True) or {}
    abs_p = str(body.get("path", ""))
    ok, jie_guo = yi_ge_shan_chu(abs_p)
    if ok:
        return jsonify({"ok": True, "xin_xi": f"已移入回收站：99-回收站\\{jie_guo}"})
    # 区分错误类型给状态码
    dai_ma = 403 if "不在文档库" in jie_guo else (400 if "已在回收站" in jie_guo else 404)
    return jsonify({"ok": False, "cuo_wu": jie_guo}), dai_ma


@wen_jian_bp.post("/pi_liang_shan_chu")
def pi_liang_shan_chu():
    """批量删除。body: {paths: [绝对路径, ...]}
    逐个移入回收站并清理索引，返回成功/失败明细。"""
    body = request.get_json(force=True) or {}
    paths = [str(p) for p in (body.get("paths") or [])]
    if not paths:
        return jsonify({"ok": False, "cuo_wu": "参数不对"}), 400
    if len(paths) > 500:
        return jsonify({"ok": False, "cuo_wu": "一次最多删 500 个"}), 400
    ok, shi_bai = 0, []
    for i, p in enumerate(paths):
        cheng_gong, xin_xi = yi_ge_shan_chu(p, xu_hao=i)
        if cheng_gong:
            ok += 1
        else:
            ming = os.path.basename(p)
            shi_bai.append(f"{ming}（{xin_xi}）")
    return jsonify({"ok": True, "cheng_gong": ok, "shi_bai": shi_bai})


@wen_jian_bp.post("/shan_chu_mulu")
def shan_chu_mulu():
    """删除文件夹（含全部内容）：整个文件夹移入回收站（保留内部结构），
    逐个清理向量/台账并记日志。body: {path: 文件夹绝对路径}"""
    body = request.get_json(force=True) or {}
    abs_d = str(body.get("path", "")).strip()

    gen = os.path.abspath(config.WEN_DANG_KU)
    if not os.path.isabs(abs_d):
        abs_d = os.path.join(gen, abs_d)
    d = os.path.abspath(abs_d)
    # 安全检查 1：必须是文档库内的真实目录，且不能是根目录本身
    try:
        zai_ku_nei = os.path.commonpath([gen, d]) == gen
    except ValueError:
        zai_ku_nei = False
    if not zai_ku_nei or d == gen or not os.path.isdir(d):
        return jsonify({"ok": False, "cuo_wu": "目录不存在或不在文档库内"}), 403
    rel_d = os.path.relpath(d, gen).replace(os.sep, "/")

    # 安全检查 2：保护清单 —— 收件箱、回收站 不允许删除（固定台账已放开删除保护）
    if rel_d.split("/")[0] in ("00-收件箱", "99-回收站"):
        return jsonify({"ok": False, "cuo_wu": "收件箱和回收站不能删除"}), 400

    # 收集文件夹内所有文件（含子目录）
    wen_jian_lie = []
    for dp, ds, fs in os.walk(d):
        for f in fs:
            if f.startswith("~$"):
                continue
            fp = os.path.join(dp, f)
            wen_jian_lie.append((os.path.relpath(fp, gen), fp))

    # 整体移入回收站（时间戳前缀，保留内部目录结构）
    os.makedirs(HUI_SHOU_ZHAN, exist_ok=True)
    hui_shou_ming = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_") + os.path.basename(d)
    hui_shou_path = os.path.join(HUI_SHOU_ZHAN, hui_shou_ming)
    try:
        shutil.move(d, hui_shou_path)
    except Exception as e:
        return jsonify({"ok": False, "cuo_wu": f"移动失败：{e}"}), 500

    # 清向量 + 清台账 + 记日志（逐文件）
    db = Session()
    try:
        for rel, fp in wen_jian_lie:
            try:
                xiang_liang_ku.shan_chu_wen_dang(rel)
            except Exception:
                pass
            db.query(WenJian).filter_by(lu_jing=rel).delete()
            db.add(GuiDangJiLu(
                yuan_lu_jing=fp,
                xin_lu_jing=os.path.join(hui_shou_path, os.path.relpath(fp, d))))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "cuo_wu": f"数据库清理失败：{e}（文件夹已在回收站）"}), 500
    finally:
        db.close()

    return jsonify({"ok": True,
                    "xin_xi": f"已移入回收站：99-回收站\\{hui_shou_ming}",
                    "wen_jian_shu": len(wen_jian_lie)})
