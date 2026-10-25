# -*- coding: utf-8 -*-
# ============================================
# 打包「可上传版本」：只收代码/文档/部署文件，排除本机数据与密钥
#
# 用法：python da_bao_shang_chuan.py
# 输出：wendangku_release.zip
#
# 排除：huan_jing（虚拟环境）、shu_ju（向量/模型/设置）、ri_zhi（日志）、
#       文档库（私人文件）、.env、__pycache__、*.log
# ============================================

import os
import zipfile

GEN = os.path.dirname(os.path.abspath(__file__))
SHU_CHU = os.path.join(GEN, "wendangku_release.zip")

# 整个目录打包
MU_LU = ["app", "kimi_work_plugin"]
# 根目录单文件打包（存在才收）
WEN_JIAN = [
    "config.py", "run.py", "mcp_server.py", "requirements.txt",
    "README.md", "配置说明.md", "使用说明.md", "功能逻辑说明.md",
    "Dockerfile", "docker-compose.yml", "start.sh", "Procfile",
    "da_bao_shang_chuan.py",
    ".env.example", ".gitignore", ".dockerignore",
    "wendangku_kimi_plugin.zip",
    # 维护脚本
    "qing_xi_chong_jian.py", "bu_gai_ming.py",
    "chong_jian_gui_zhang_fen_kuai.py", "bu_tiao_kuan_zhang_jie.py",
    "fen_xi_biao_qian.py", "fen_xi_chong_fu_gui_zhang.py",
    "zi_dong_zuo_fei_jiu_ban.py",
]
# 目录里要跳过的子目录/后缀
TIAO_GUO_MU_LU = {"__pycache__", ".pytest_cache", ".mypy_cache"}
TIAO_GUO_HOU_ZHUI = (".pyc", ".pyo", ".log")


def _jia(z, abs_p, rel_p):
    z.write(abs_p, rel_p)


def main():
    zong = 0
    with zipfile.ZipFile(SHU_CHU, "w", zipfile.ZIP_DEFLATED) as z:
        for mu in MU_LU:
            gen = os.path.join(GEN, mu)
            if not os.path.isdir(gen):
                continue
            for dp, ds, fs in os.walk(gen):
                ds[:] = [d for d in ds if d not in TIAO_GUO_MU_LU]
                for f in fs:
                    if f.endswith(TIAO_GUO_HOU_ZHUI):
                        continue
                    abs_p = os.path.join(dp, f)
                    rel_p = os.path.join("wen_dang_guan_jia", os.path.relpath(abs_p, GEN))
                    _jia(z, abs_p, rel_p)
                    zong += 1
        for f in WEN_JIAN:
            abs_p = os.path.join(GEN, f)
            if os.path.isfile(abs_p):
                _jia(z, abs_p, os.path.join("wen_dang_guan_jia", f))
                zong += 1

    da_xiao = os.path.getsize(SHU_CHU) / 1024 / 1024
    print(f"已生成：{SHU_CHU}")
    print(f"文件数：{zong}，大小：{da_xiao:.2f} MB")
    print("提醒：不要把这个 zip 和 shu_ju/、ri_zhi/、文档库/、.env 一起上传。")


if __name__ == "__main__":
    main()
