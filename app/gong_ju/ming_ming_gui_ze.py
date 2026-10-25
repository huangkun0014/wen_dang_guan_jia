# -*- coding: utf-8 -*-
# ============================================
# 命名规则工具：无AI时的兜底命名，以及所有命名都要过的基础清洗
# 规则: YYYYMMDD_主题.扩展名；日期取文件名里的，没有再取修改时间
# ============================================

import os
import re
import datetime

def qing_xi_wen_jian_ming(wen_jian_ming: str) -> str:
    """基础清洗：去掉OA系统下载的一长串数字尾缀、合并多空格。

    注意: 微信图片_/mmexport_ 后面的数字是身份标识，不能剥。
    """
    n = wen_jian_ming
    if not re.match(r"^(微信图片_|mmexport)", n):
        n = re.sub(r"_\d{10,}(?=\.[^.]+$)", "", n)      # 如 xxx_1773049128060.pdf -> xxx.pdf
    n = re.sub(r" {2,}", " ", n).strip()
    return n

def ri_qi_qian_zhui(wen_jian_lu_jing: str, wen_jian_ming: str) -> str:
    """给文件名加日期前缀。文件名里已有8位日期(YYYYMMDD)则自动挪到最前，
    没有则用文件修改日期。返回新文件名。
    """
    n = qing_xi_wen_jian_ming(wen_jian_ming)
    kuo_zhan_ming = os.path.splitext(n)[1]
    zhu_ti = n[: len(n) - len(kuo_zhan_ming)]
    if re.match(r"^20\d{6}_", zhu_ti):
        return n                                        # 已有规范前缀，不动
    m = re.search(r"(20\d{6})", zhu_ti)
    if m:
        ri_qi = m.group(1)
        zhu_ti = zhu_ti.replace(ri_qi, "", 1).strip("_- ")
    else:
        ri_qi = datetime.datetime.fromtimestamp(os.path.getmtime(wen_jian_lu_jing)).strftime("%Y%m%d")
    if not zhu_ti:
        zhu_ti = "未命名"
    return f"{ri_qi}_{zhu_ti}{kuo_zhan_ming}"

def bi_kai_chong_ming(mu_lu: str, wen_jian_ming: str) -> str:
    """目标位置已有同名文件时自动追加 _2 _3，绝不让文件被覆盖。"""
    mu_biao = os.path.join(mu_lu, wen_jian_ming)
    if not os.path.exists(mu_biao):
        return mu_biao
    kuo_zhan_ming = os.path.splitext(wen_jian_ming)[1]
    zhu_ti = wen_jian_ming[: len(wen_jian_ming) - len(kuo_zhan_ming)]
    i = 2
    while os.path.exists(os.path.join(mu_lu, f"{zhu_ti}_{i}{kuo_zhan_ming}")):
        i += 1
    return os.path.join(mu_lu, f"{zhu_ti}_{i}{kuo_zhan_ming}")

def _he_fa_ri_qi(ri_qi: str) -> bool:
    try:
        datetime.datetime.strptime(ri_qi, "%Y%m%d")
        return True
    except ValueError:
        return False


def gui_fan_hua_ming(abs_p: str, xin_ming: str) -> str:
    """把 AI 给的文件名规范成 YYYYMMDD_主题.扩展名（只处理名字，不碰文件）。

    - 扩展名强制与原文件一致
    - 日期前缀必须是合法 8 位；AI 只给 202610、2026.10 这类残片时，
      用原文件名里的 8 位日期，没有就用修改时间补齐
    - 主题为空时退回原文件名
    """
    yuan = os.path.basename(abs_p)
    kzm = os.path.splitext(yuan)[1]
    ming = re.sub(r'[\\/:*?"<>|\r\n]+', "", str(xin_ming or "")).strip()
    if not ming:
        return yuan
    if os.path.splitext(ming)[1].lower() != kzm.lower():
        zhu_ti = os.path.splitext(ming)[0].strip()
        if not zhu_ti:
            return yuan
        ming = zhu_ti + kzm
    zhu_ti = os.path.splitext(ming)[0]
    m = re.match(r"^(20\d{6})_", zhu_ti)
    if not m or not _he_fa_ri_qi(m.group(1)):
        # 剥掉不完整的日期残片（202610_ / 2026.10.0_ / 2026年10月）
        zhu_ti = re.sub(
            r"^20\d{2}[年.\-_/]?(?:1[0-2]|0?[1-9])[月.\-_/]?"
            r"(?:3[01]|[12]\d|0?[1-9])?[日]?[_\-\s]*",
            "", zhu_ti)
        zhu_ti = re.sub(r"^\d{1,2}[_.\-\s]+", "", zhu_ti).strip("_- ")
        if not zhu_ti:
            return yuan
        my = re.search(r"(20\d{6})", os.path.splitext(yuan)[0])
        if my and _he_fa_ri_qi(my.group(1)):
            ri_qi = my.group(1)
        else:
            try:
                ri_qi = datetime.datetime.fromtimestamp(
                    os.path.getmtime(abs_p)).strftime("%Y%m%d")
            except OSError:
                ri_qi = datetime.datetime.now().strftime("%Y%m%d")
        ming = f"{ri_qi}_{zhu_ti}{kzm}"
    return ming


def wen_jian_ming_you_yu_yi(ma: str) -> bool:
    """判断文件名主题是否有语义。无语义的典型: 新建文档、scan、img、截图、下载等。"""
    kuo_zhan_ming = os.path.splitext(ma)[1]
    zhu_ti = ma[: len(ma) - len(kuo_zhan_ming)]
    han_zi_shu = len(re.findall(r"[\u4e00-\u9fff]", zhu_ti))
    if han_zi_shu >= 4:
        return True
    if re.match(r"^(新建|scan$|image|img|qq|wx|download|下载|未命名|screenshot|屏幕截图)", zhu_ti, re.I):
        return False
    return len(zhu_ti.strip()) >= 6                     # 纯英文至少6个字符才算有意义

# 文件名里不允许出现的字符（Windows 非法字符 + 常见全角变体）
_FEI_FA_ZI_FU = re.compile(r'[\\/:*?"<>|＼／：＊？＂＜＞｜]')


def shen_he_gui_fan(abs_p: str, wen_jian_ming: str):
    """批量规范命名用的规则检查：看现有文件名是否规范，并给出规则能改出的规范名。

    返回 (wen_ti, gui_fan_ming)：
      wen_ti       - 问题列表，空列表 = 已合规（此时 gui_fan_ming 为 None，不需要改）
      gui_fan_ming - 按规则清洗后的规范名；None = 规则改不动（占位名/无语义），需 AI 按内容起名
    只动规则确定能改对的：补日期前缀、剥OA尾缀、清非法字符、去多余空格。
    占位名（新建文档/scan/img 之类）规则改了也是白改，直接标记为"规则改不动"，交给 AI。
    """
    wen_ti = []
    yuan = wen_jian_ming
    qing_xi = qing_xi_wen_jian_ming(yuan)

    # 1. OA 下载尾缀
    if qing_xi != yuan:
        wen_ti.append("带OA系统下载的数字尾缀")
    # 2. 非法字符
    if _FEI_FA_ZI_FU.search(yuan):
        wen_ti.append("含非法字符（\\/:*?\"<>|）")
        qing_xi = _FEI_FA_ZI_FU.sub("_", qing_xi)
    # 3. 多余空格/首尾空格
    if yuan != yuan.strip() or "  " in yuan:
        wen_ti.append("含多余空格")

    # 4. 占位名检查：新建/scan/img/截图 这类名字，规则改不出有意义的名字，交给 AI
    kuo_zhan_ming = os.path.splitext(qing_xi)[1]
    zhu_ti = qing_xi[: len(qing_xi) - len(kuo_zhan_ming)].strip("_- ")
    if zhu_ti and re.match(r"^(新建|scan$|image|img$|qq|wx_|download|下载|未命名|screenshot|屏幕截图)", zhu_ti, re.I):
        wen_ti.append("主题是无意义占位名（需AI按内容起名）")
        return wen_ti, None                   # 规则改不动

    # 5. 日期前缀：清洗后套上规则（已有前缀会自动跳过，文件名里有日期会自动前置）
    if re.match(r"^20\d{6}_", zhu_ti):
        gui_fan = f"{zhu_ti}{kuo_zhan_ming}"
        if qing_xi != yuan:
            wen_ti.append("日期前缀位置不规范")
    else:
        ri_qi_m = re.search(r"(20\d{6})", zhu_ti)
        if ri_qi_m:
            wen_ti.append("有8位日期但未放在最前面")
        else:
            wen_ti.append("缺少日期前缀")
        gui_fan = ri_qi_qian_zhui(abs_p, qing_xi)

    if not wen_ti:
        return [], None                       # 完全合规
    if gui_fan == yuan:
        gui_fan = None                        # 规则改不动
    return wen_ti, gui_fan
