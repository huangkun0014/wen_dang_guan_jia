# -*- coding: utf-8 -*-
# ============================================
# 补条款/章节标识（P1，不重新嵌入）
#
# 分块库里已有的块，如果 tiao_kuan 为空，就从块文本里识别：
#   第X条 > 第X章/节 > 行首"五、标题" > 行首"（一）标题"
# 然后只更新 Chroma 的 metadata，不重算向量（很快，几秒到几十秒）。
#
# 用法（建议先关文档库服务，避免两个进程同时写 Chroma）：
#   python bu_tiao_kuan_zhang_jie.py
# ============================================

import time

import config
from app.gong_ju import xiang_liang_ku


def main():
    col = xiang_liang_ku._qu_kuai_collection()
    zong = col.count()
    print(f"分块库共 {zong} 块，读取中…", flush=True)
    jie = col.get(include=["documents", "metadatas"])
    ids = jie.get("ids") or []
    docs = jie.get("documents") or []
    mds = jie.get("metadatas") or []

    geng_xin_ids, geng_xin_mds = [], []
    bian = 0
    for i, doc_id in enumerate(ids):
        md = dict(mds[i] or {})
        kuai = docs[i] if i < len(docs) else ""
        xin = xiang_liang_ku._qu_tiao_kuan(kuai)
        if xin and xin != md.get("tiao_kuan", ""):
            md["tiao_kuan"] = xin
            geng_xin_ids.append(doc_id)
            geng_xin_mds.append(md)
            bian += 1

    print(f"需要更新 {bian} 块，开始写回…", flush=True)
    kai = time.time()
    for i in range(0, len(geng_xin_ids), 500):
        col.update(ids=geng_xin_ids[i:i + 500],
                   metadatas=geng_xin_mds[i:i + 500])
        print(f"  已写 {min(i + 500, len(geng_xin_ids))}/{len(geng_xin_ids)}", flush=True)
    print(f"完成：更新 {bian} 块，耗时 {time.time() - kai:.1f} 秒", flush=True)


if __name__ == "__main__":
    main()
