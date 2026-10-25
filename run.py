# -*- coding: utf-8 -*-
# ============================================
# 文档库管家 - 唯一入口
# 启动: python run.py
# ============================================

import os
import config

# 日志目录提前建好
os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)

from app import chuang_jian_ying_yong

app = chuang_jian_ying_yong()

if __name__ == "__main__":
    host = config.FU_WU_HOST
    print(f"文档库管家启动中: http://{host}:{config.FU_WU_DUAN_KOU}")
    print(f"管理目录: {config.WEN_DANG_KU}")
    print(f"台账库: {config.DB_LEI_XING}")
    print("关闭本窗口即停止服务")
    # threaded=True 允许索引线程和网页请求并行
    app.run(host=host, port=config.FU_WU_DUAN_KOU, threaded=True)
