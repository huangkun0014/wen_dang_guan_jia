# -*- coding: utf-8 -*-
# ============================================
# 规章近似重复分析（只读）
#
# 找出标题高度相似（字符二元组 Jaccard >= 0.85）的规章，
# 输出建议报告，人工确认是否合并/删除。不自动改数据。
#
# 用法：python fen_xi_chong_fu_gui_zhang.py [阈值，默认0.85]
# 输出：ri_zhi/gui_zhang_chong_fu_jian_yi.md
# ============================================

import os
import re
import sys
import collections

import config
from app.moxing import Session, WenJian

YU_ZHI = float(sys.argv[1]) if len(sys.argv) > 1 else 0.85
SHU_CHU = os.path.join(config.RI_ZHI_MU_LU, "gui_zhang_chong_fu_jian_yi.md")


def _gui_fan(ming: str) -> str:
    s = re.sub(r"^\d{8}_", "", ming or "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"^附件\d+[_\-]?", "", s)
    s = re.sub(r"[（(](试行|暂行|修订版)[)）]", "", s)
    s = re.sub(r"(重新)?(印发|修订|修改|公布|发布)?(通知|通报)$", "", s)
    s = re.sub(r"(修订版|修改版|试行|暂行)$", "", s)
    s = re.sub(r"_\d+$", "", s)
    return s.strip("_- ")


def _bigrams(s: str) -> set:
    s = re.sub(r"[\s\W_]+", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    db = Session()
    try:
        hang = db.query(WenJian).filter(WenJian.wen_zhong == "规章制度").all()
        rows = [(h.wen_jian_ming, h.lu_jing, h.you_xiao or "未知") for h in hang]
    finally:
        db.close()

    # 先按归一标题分组（完全同名）
    zu = collections.defaultdict(list)
    for ming, rel, you in rows:
        zu[_gui_fan(ming)].append((ming, rel, you))

    # 再找标题高度相似的组
    titles = sorted(zu)
    bg = {t: _bigrams(t) for t in titles}
    xiang_si = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            fen = _jaccard(bg[titles[i]], bg[titles[j]])
            if fen >= YU_ZHI:
                xiang_si.append((fen, titles[i], titles[j]))
    xiang_si.sort(reverse=True)

    os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)
    with open(SHU_CHU, "w", encoding="utf-8") as f:
        f.write("# 规章重复/近似重复建议（只读分析）\n\n")
        f.write(f"- 规章总数：{len(rows)}\n")
        f.write(f"- 归一标题数：{len(titles)}\n")
        f.write(f"- 近似标题对（Jaccard ≥ {YU_ZHI}）：{len(xiang_si)}\n\n")

        f.write("## 一、同名多版本（会由检索层标最新/旧版）\n\n")
        for t, v in sorted(zu.items()):
            if len(v) <= 1:
                continue
            f.write(f"### {t}（{len(v)} 个文件）\n")
            for ming, rel, you in sorted(v):
                f.write(f"- {ming}｜{rel}｜有效性：{you}\n")
            f.write("\n")

        f.write("## 二、标题高度相似（建议人工确认是否同一制度）\n\n")
        if not xiang_si:
            f.write("没有。\n")
        for fen, a, b in xiang_si:
            f.write(f"### 相似度 {fen:.2f}\n")
            for t in (a, b):
                for ming, rel, you in zu[t]:
                    f.write(f"- {ming}｜{rel}｜有效性：{you}\n")
            f.write("\n")

        f.write("## 三、说明\n\n")
        f.write("- 本报告只做分析，没有改任何数据。\n")
        f.write("- 同名多版本已由检索层自动标最新/旧版；这里列出供核对。\n")
        f.write("- 近似标题可能是同一制度的不同写法，也可能是不同文件，合并前需看正文。\n")

    print(f"完成：{SHU_CHU}；同名组 "
          f"{sum(1 for v in zu.values() if len(v) > 1)}，近似对 {len(xiang_si)}")


if __name__ == "__main__":
    main()
