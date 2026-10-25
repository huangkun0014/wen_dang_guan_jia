# -*- coding: utf-8 -*-
# ============================================
# 同名旧版自动作废（幂等，可重复跑）
#
# 规则：
#   - 同名、不同日期：只保留最新日期那份，其余 you_xiao='作废'；
#   - 同名、同日期（重复副本）：保留文件名最短/不带 _2 后缀的那份，其余作废；
#   - 不同标题的文件不处理（避免误伤仍现行有效的旧制度）。
#
# 用法：python zi_dong_zuo_fei_jiu_ban.py
# ============================================

from app.gong_ju import wen_zhong_fu_wu

if __name__ == "__main__":
    print(wen_zhong_fu_wu.zi_dong_zuo_fei_jiu_ban())
