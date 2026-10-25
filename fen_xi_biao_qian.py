# -*- coding: utf-8 -*-
# ============================================
# 标签归一分析（P3，只读，不改数据）
#
# 目标：2900 多个标签里有大量同义/近义/大小写重复，先找出可合并的组，
#       输出建议报告，人工确认后再决定是否应用（避免自动合并丢语义）。
#
# 做法：
#   1. 统计每个标签的文件数；
#   2. 规范化（去空格/括号/大小写）找完全重复；
#   3. 用本地 bge-m3 把标签转成向量，余弦相似度 >= 阈值 的聚成一簇；
#   4. 每簇建议保留"文件数最多"的那个标签，其余作为别名。
#
# 用法：python fen_xi_biao_qian.py [阈值，默认0.90]
# 输出：ri_zhi/biao_qian_gui_yi_jian_yi.md
# ============================================

import os
import re
import sys
import collections

import numpy as np

import config
from app.moxing import Session, WenJian
from app.gong_ju import xiang_liang_ku

YU_ZHI = float(sys.argv[1]) if len(sys.argv) > 1 else 0.90
SHU_CHU = os.path.join(config.RI_ZHI_MU_LU, "biao_qian_gui_yi_jian_yi.md")


def _jia_zai():
    db = Session()
    try:
        ji = collections.Counter()
        for h in db.query(WenJian).all():
            for t in re.split(r"[,，;；、]", h.biao_qian or ""):
                t = t.strip()
                if t:
                    ji[t] += 1
    finally:
        db.close()
    return ji


def _gui_fan(t: str) -> str:
    return re.sub(r"[\s\-_（）()【】\[\]·]+", "", t).lower()


def _xiang_liang(tags):
    vec = np.array(xiang_liang_ku._bian_liang(tags), dtype=np.float32)
    ju = np.linalg.norm(vec, axis=1, keepdims=True)
    ju[ju == 0] = 1
    return vec / ju


def _ju_lei(sim, yu_zhi):
    """并查集：相似度 >= 阈值的标签连成一簇。"""
    n = sim.shape[0]
    fu = list(range(n))

    def zhao(x):
        while fu[x] != x:
            fu[x] = fu[fu[x]]
            x = fu[x]
        return x

    def he(x, y):
        rx, ry = zhao(x), zhao(y)
        if rx != ry:
            fu[ry] = rx

    # 只取上三角，避免重复
    for i, j in np.argwhere(np.triu(sim, 1) >= yu_zhi):
        he(int(i), int(j))
    zu = collections.defaultdict(list)
    for i in range(n):
        zu[zhao(i)].append(i)
    return [v for v in zu.values() if len(v) > 1]


def main():
    ji = _jia_zai()
    tags = list(ji)
    print(f"标签 {len(tags)} 个，总出现 {sum(ji.values())} 次；正在向量化…", flush=True)
    vec = _xiang_liang(tags)
    sim = vec @ vec.T
    print("正在聚类…", flush=True)
    zu_lie = _ju_lei(sim, YU_ZHI)

    # 完全重复（规范化后相同）
    norm = collections.defaultdict(list)
    for t in tags:
        norm[_gui_fan(t)].append(t)
    chong_fu = {k: v for k, v in norm.items() if len(v) > 1}

    # 簇内按文件数排序，保留最多的
    xiang = []
    for zu in zu_lie:
        cheng_yuan = sorted(((tags[i], ji[tags[i]]) for i in zu),
                            key=lambda x: (-x[1], len(x[0])))
        if len(cheng_yuan) < 2:
            continue
        xiang.append(cheng_yuan)
    xiang.sort(key=lambda c: -sum(x[1] for x in c))

    os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)
    with open(SHU_CHU, "w", encoding="utf-8") as f:
        f.write("# 标签归一建议（只读分析）\n\n")
        f.write(f"- 标签总数：{len(tags)}\n")
        f.write(f"- 只出现 1 次的标签：{sum(1 for v in ji.values() if v == 1)}\n")
        f.write(f"- 相似度阈值：{YU_ZHI}\n")
        f.write(f"- 可合并簇：{len(xiang)}\n\n")

        f.write("## 一、写法重复（大小写/空格/括号）\n\n")
        if not chong_fu:
            f.write("没有。\n\n")
        for k, v in chong_fu.items():
            f.write(f"- {k}：" + "、".join(f"{t}({ji[t]})" for t in v) + "\n")
        f.write("\n## 二、语义相近、建议合并的簇\n\n")
        f.write("| 建议保留 | 可合并为别名（文件数） | 影响文件数 |\n|---|---|---|\n")
        for cheng_yuan in xiang[:300]:
            zhu = cheng_yuan[0][0]
            bie = "、".join(f"{t}({c})" for t, c in cheng_yuan[1:])
            f.write(f"| {zhu}({cheng_yuan[0][1]}) | {bie} | {sum(c for _, c in cheng_yuan)} |\n")

        f.write("\n## 三、说明\n\n")
        f.write("- 本报告只做分析，没有改任何数据。\n")
        f.write("- 合并会改变搜索词和标签统计，建议先挑影响面大的簇人工确认。\n")
        f.write("- 确认后可写一个白名单脚本批量替换（保留原标签作为别名或直接覆盖）。\n")

    print(f"完成，报告：{SHU_CHU}；可合并簇 {len(xiang)} 个", flush=True)


if __name__ == "__main__":
    main()
