# -*- coding: utf-8 -*-
# ============================================
# 补改名工具：处理上次全量重建时"文件被占用"导致失败的文件
#
# 读取 ri_zhi/chong_jian_shi_bai.log，对仍存在的文件：
#   - 库内文件：重新 AI 规范命名 + 重建它的向量/分块
#   - 收件箱文件：重新 AI 命名 + 归档到年份目录 + 建索引
#
# 用法（在项目根目录）：
#   1. 先重启文档库管家（释放旧进程的文件句柄、加载修复后的代码）
#   2. python bu_gai_ming.py
# 失败项会继续追加到同一个日志，可再次运行。
# ============================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from app.moxing import Session, WenJian
from app.gong_ju import suo_yin_fu_wu, ming_ming_gui_ze

RI_ZHI = os.path.join(config.RI_ZHI_MU_LU, "chong_jian_shi_bai.log")


def _du_qu_shi_bai_lu_jing():
    """从失败日志里取仍存在的文件路径（去重）。"""
    if not os.path.exists(RI_ZHI):
        return []
    lu_jing, yi_you = [], set()
    for line in open(RI_ZHI, encoding="utf-8"):
        bu_fen = line.rstrip("\n").split("\t")
        if len(bu_fen) < 3:
            continue
        p = bu_fen[2]
        if p in yi_you:
            continue
        yi_you.add(p)
        if os.path.isfile(p):
            lu_jing.append((bu_fen[1], p))
    return lu_jing


def main():
    ren_wu = _du_qu_shi_bai_lu_jing()
    print(f"失败日志里仍存在的文件：{len(ren_wu)} 个")
    if not ren_wu:
        print("没有需要补处理的文件。")
        return

    cheng_gong, shi_bai = 0, []
    shou_jian_xiang = os.path.abspath(config.SHOU_JIAN_XIANG)

    for lei_xing, p in ren_wu:
        ming = os.path.basename(p)
        print(f"\n>>> {ming}（{lei_xing}）")
        try:
            if os.path.abspath(p).startswith(shou_jian_xiang + os.sep):
                # 收件箱文件：命名+归档，再同步建索引
                from app.lan_tu.shou_jian_xiang.views import _jian_yi_yi_ge, _gui_dang_yi_ge
                jian_yi = _jian_yi_yi_ge(p)
                if not jian_yi.get("ok"):
                    raise RuntimeError(jian_yi.get("cuo_wu", "AI 分析失败"))
                xin_ming = ming_ming_gui_ze.gui_fan_hua_ming(p, jian_yi["wen_jian_ming"])
                ok, jie_guo = _gui_dang_yi_ge(
                    p, xin_ming, jian_yi.get("zhai_yao", ""),
                    jian_yi.get("biao_qian", ""), jian_suo_yin=False)
                if not ok:
                    raise RuntimeError(jie_guo.get("cuo_wu", "归档失败"))
                xin_abs = jie_guo["xin_lu_jing"]
                xin_rel = os.path.relpath(xin_abs, config.WEN_DANG_KU)
                jie = suo_yin_fu_wu.wen_jian_suo_yin((xin_rel, xin_abs))
                print(f"    已归档并索引：{os.path.basename(xin_abs)}（{jie}）")
            else:
                # 库内文件：强制重新处理，AI 改名 + 重建向量/分块
                rel = os.path.relpath(p, config.WEN_DANG_KU)
                db = Session()
                try:
                    hang = db.query(WenJian).filter_by(lu_jing=rel).first()
                    if hang is not None:
                        hang.you_xiang_liang = 0
                        db.commit()
                finally:
                    db.close()
                jie = suo_yin_fu_wu.wen_jian_suo_yin((rel, p), ai_ming=True)
                print(f"    重新处理完成：{jie}")
            cheng_gong += 1
        except Exception as e:
            shi_bai.append(f"{ming}: {e}")
            print(f"    失败：{e}")

    print(f"\n完成：成功 {cheng_gong}，失败 {len(shi_bai)}")
    for x in shi_bai:
        print("  -", x)
    if shi_bai:
        print("\n提示：确认 WPS/Excel/Word 已关闭、没有网盘同步在扫描，然后可再次运行本脚本。")


if __name__ == "__main__":
    main()
