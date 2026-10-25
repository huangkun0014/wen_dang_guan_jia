# -*- coding: utf-8 -*-
# ============================================
# 文件操作重试：Windows 下文件常被 WPS/杀毒/系统索引短暂占用
# （WinError 32：另一个程序正在使用此文件，进程无法访问）
# 改名/移动统一走这里：遇到占用按 0.8s、1.6s、2.4s… 退避重试
# ============================================

import os
import shutil
import time


def _ke_zhong_shi(e: OSError) -> bool:
    """是否是"文件被占用"类错误（可重试）。"""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) == 32


def chong_shi(cao_zuo, ci_shu: int = 5, jian_ge: float = 0.8):
    """执行文件操作，被占用时退避重试。返回 (是否成功, 结果或异常)。"""
    for i in range(ci_shu):
        try:
            return True, cao_zuo()
        except OSError as e:
            if not _ke_zhong_shi(e) or i == ci_shu - 1:
                return False, e
            time.sleep(jian_ge * (i + 1))
    return False, None


def gai_ming(yuan: str, mu_biao: str, ci_shu: int = 5):
    """带重试的 os.rename。"""
    return chong_shi(lambda: os.rename(yuan, mu_biao), ci_shu)


def yi_dong(yuan: str, mu_biao: str, ci_shu: int = 5):
    """带重试的 shutil.move（跨目录/跨盘都支持）。"""
    return chong_shi(lambda: shutil.move(yuan, mu_biao), ci_shu)
