# -*- coding: utf-8 -*-
# ============================================
# 重建"规章制度"类文件的分块向量（P2）
#
# 目的：给规章的每个块补 wen_zhong / tiao_kuan 元数据，
#       搜索时能显示"命中条款：第X条"，并能按文种过滤。
#
# 只处理 wen_zhong='规章制度' 的文件；不动的文件不会重复嵌入。
# 运行前建议先关闭文档库服务（避免两个进程同时写 Chroma）。
# 用法：
#   python chong_jian_gui_zhang_fen_kuai.py            # 只补缺元数据的
#   python chong_jian_gui_zhang_fen_kuai.py --qiang-zhi  # 全部重做
# ============================================

import os
import sys
import time

import config
from app.moxing import Session, WenJian
from app.gong_ju import suo_yin_fu_wu, xiang_liang_ku

QING_ZHI = "--qiang-zhi" in sys.argv
ZHI_PDF = "--pdf" in sys.argv


def _yi_you_tiao_kuan(rel: str) -> bool:
    """分块库里这条文件的块是否已经带 tiao_kuan 元数据。"""
    try:
        col = xiang_liang_ku._qu_kuai_collection()
        jie = col.get(where={"lu_jing": rel}, limit=1, include=["metadatas"])
        mds = jie.get("metadatas") or []
        return bool(mds and "tiao_kuan" in (mds[0] or {}))
    except Exception:
        return False


def main():
    db = Session()
    try:
        hang_lie = db.query(WenJian).filter(WenJian.wen_zhong == "规章制度").all()
        if ZHI_PDF:
            hang_lie = [h for h in hang_lie
                        if (h.wen_jian_ming or "").lower().endswith(".pdf")]
        ren_wu = [(h.lu_jing, h.wen_jian_ming) for h in hang_lie]
    finally:
        db.close()

    print(f"规章制度共 {len(ren_wu)} 个，开始重建分块索引…", flush=True)
    cheng_gong = tiao_guo = shi_bai = 0
    cuo_wu = []
    kai_shi = time.time()

    for i, (rel, ming) in enumerate(ren_wu, 1):
        if not QING_ZHI and _yi_you_tiao_kuan(rel):
            tiao_guo += 1
            continue
        abs_p = os.path.join(config.WEN_DANG_KU, (rel or "").replace("\\", os.sep))
        if not os.path.isfile(abs_p):
            shi_bai += 1
            cuo_wu.append((rel, "文件不存在"))
            continue
        try:
            jie = suo_yin_fu_wu.wen_jian_suo_yin((rel, abs_p), ai_ming=False,
                                                qiang_zhi=True)
            if jie == "cuo_wu":
                shi_bai += 1
                cuo_wu.append((rel, "索引返回 cuo_wu"))
            else:
                cheng_gong += 1
        except Exception as e:
            shi_bai += 1
            cuo_wu.append((rel, str(e)[:200]))
        if i % 5 == 0 or i == len(ren_wu):
            print(f"[{i}/{len(ren_wu)}] 成功{cheng_gong} 跳过{tiao_guo} 失败{shi_bai}", flush=True)

    hao_shi = time.time() - kai_shi
    print(f"完成：成功{cheng_gong} 跳过{tiao_guo} 失败{shi_bai}，耗时{hao_shi/60:.1f}分钟", flush=True)
    if cuo_wu:
        lu_jing = os.path.join(config.RI_ZHI_MU_LU, "gui_zhang_fen_kuai_shi_bai.log")
        with open(lu_jing, "w", encoding="utf-8") as f:
            for rel, cuo in cuo_wu:
                f.write(f"{rel}\t{cuo}\n")
        print("失败明细：" + lu_jing, flush=True)


if __name__ == "__main__":
    main()
