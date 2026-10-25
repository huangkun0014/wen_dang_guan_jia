# -*- coding: utf-8 -*-
# ============================================
# 索引服务：扫描文档库 -> 提取文本 -> 建向量 + 更新数据库
# 被 suo_yin 蓝图调用，放后台线程跑，不阻塞网页
#
# 两层索引：
#   文件级向量（wen_dang 集合）——位置+归口+文件名+标签+正文，用于"整篇相关"
#   分块向量（wen_dang_kuai 集合）——正文按段落切块分别嵌入，用于"精确命中段落"
# ============================================

import os
import re
import datetime
import threading
import config
from app.moxing import Session, WenJian, GuiDangJiLu
from app.gong_ju import (wen_jian_ti_qu, xiang_liang_ku, ming_ming_gui_ze,
                         wen_jian_cao_zuo, wen_zhong_fu_wu)

# 改名失败计数 + 失败明细日志（Windows 文件被占用时记录，便于重跑）
_shi_bai_ming = 0
_shi_bai_ri_zhi = os.path.join(config.RI_ZHI_MU_LU, "chong_jian_shi_bai.log")


def _ji_shi_bai(lei_xing: str, lu_jing: str, cuo_wu: str):
    try:
        os.makedirs(config.RI_ZHI_MU_LU, exist_ok=True)
        with open(_shi_bai_ri_zhi, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{lei_xing}\t{lu_jing}\t{cuo_wu}\n")
    except Exception:
        pass


def _an_tiao_qie(wen_ben: str, tiao_biao: list, kuai_chang: int,
                 chong_die: int, zui_duo: int) -> list:
    """规章类按"第X条"切块：每条一块（过长的条再硬切），每块带文档标题。"""
    biao_ti = wen_ben.strip().split("\n", 1)[0].strip()[:40]
    kuai = []
    # 第一条之前的引言（取尾部，含制定目的等）
    tou = wen_ben[:tiao_biao[0].start()].strip()
    if tou:
        kuai.append(tou[-kuai_chang:])
    for i, m in enumerate(tiao_biao):
        qi = m.start()
        zhi = tiao_biao[i + 1].start() if i + 1 < len(tiao_biao) else len(wen_ben)
        tiao = wen_ben[qi:zhi].strip()
        if not tiao:
            continue
        if len(tiao) <= kuai_chang:
            kuai.append(f"{biao_ti}\n{tiao}"[:kuai_chang + 60] if biao_ti else tiao)
        else:
            bu = max(1, kuai_chang - chong_die)
            for j in range(0, len(tiao), bu):
                pian = tiao[j:j + kuai_chang]
                if pian.strip():
                    kuai.append(f"{biao_ti}\n{pian}"[:kuai_chang + 60] if biao_ti else pian)
        if len(kuai) >= zui_duo:
            break
    return kuai[:zui_duo]


def _qie_kuai(wen_ben: str, kuai_chang: int = None,
              chong_die: int = None, zui_duo: int = None,
              gui_zhang: bool = False) -> list:
    """把长文本切成约 kuai_chang 字的小块（块间带重叠）。

    目的：一个文件一个向量会把多主题"摊薄"，长文档后面的内容也进不了索引；
    切块后每块单独嵌入，搜索能定位到具体段落。

    规章类（标签含"规章制度"或正文出现 ≥8 个"第X条"）走**按条切块**：
    合规核对时能拿到完整条款，不会被 450 字硬切截断。
    """
    kuai_chang = kuai_chang or getattr(config, "FEN_KUAI_ZI_SHU", 450)
    chong_die = chong_die or getattr(config, "FEN_KUAI_CHONG_DIE", 60)
    zui_duo = zui_duo or getattr(config, "FEN_KUAI_ZUI_DUO", 80)

    wen_ben = re.sub(r"[ \t]+", " ", (wen_ben or "").strip())
    if not wen_ben:
        return []

    # 规章类：优先按"第X条"切（至少 3 条才值得按条切）
    tiao_biao = list(re.finditer(r"第[一二三四五六七八九十百千0-9０-９]+条", wen_ben))
    if len(tiao_biao) >= 3 and (gui_zhang or len(tiao_biao) >= 8):
        tiao_kuai = _an_tiao_qie(wen_ben, tiao_biao, kuai_chang, chong_die, zui_duo)
        if tiao_kuai:
            return tiao_kuai

    duan_lie = [d.strip() for d in re.split(r"\n+", wen_ben) if d.strip()]
    kuai, dang_qian = [], ""
    for d in duan_lie:
        # 超长段落先硬切
        while len(d) > kuai_chang:
            if dang_qian:
                kuai.append(dang_qian)
                dang_qian = ""
            kuai.append(d[:kuai_chang])
            d = d[kuai_chang:]
        if not d:
            continue
        if len(dang_qian) + len(d) + 1 <= kuai_chang:
            dang_qian = (dang_qian + "\n" + d).strip()
        else:
            if dang_qian:
                kuai.append(dang_qian)
            dang_qian = d
        if len(kuai) >= zui_duo:
            break
    if dang_qian and len(kuai) < zui_duo:
        kuai.append(dang_qian)

    # 块间加重叠：把上一块尾部拼到下一块开头，避免关键句正好被切断
    if chong_die > 0:
        for i in range(1, len(kuai)):
            tou = kuai[i - 1][-chong_die:]
            kuai[i] = (tou + "\n" + kuai[i])[:kuai_chang + chong_die]
    return kuai[:zui_duo]

# 索引进度（内存态，前端轮询读取）
jin_du = {
    "yun_xing_zhong": False,     # 是否有索引任务在跑
    "zong_shu": 0,               # 本次要处理的文件总数
    "wan_cheng": 0,              # 已完成数
    "xin_zeng": 0,               # 新建向量数
    "tiao_guo": 0,               # 跳过数（没变过）
    "cuo_wu": 0,                 # 失败数
    "gai_ming_shi_bai": 0,       # 重建时 AI 改名失败数（文件被占用等，明细见日志）
    "zui_hou_xin_xi": "",        # 最后一行状态说明
}


def sao_miao_lie_biao():
    """遍历文档库，返回 [(相对路径, 绝对路径)]，跳过收件箱和待清理。"""
    jie_guo = []
    for dp, ds, fs in os.walk(config.WEN_DANG_KU):
        ds[:] = [d for d in ds if not d.startswith("99-") and d != "00-收件箱"]
        for f in fs:
            if f.startswith("~$") or f == "文件索引总表.xlsx":
                continue
            abs_p = os.path.join(dp, f)
            rel = os.path.relpath(abs_p, config.WEN_DANG_KU)
            jie_guo.append((rel, abs_p))
    return jie_guo


def _ai_gui_fan_ming(rel: str, abs_p: str, wen_ben: str):
    """给一个文件用 AI 起规范名并直接改名（保留台账标签/摘要）。

    返回 (新相对路径, 新绝对路径)；AI 失败/名字没变/改名失败时原样返回。
    只会改文件名，不移动目录；重名自动加 _2，绝不覆盖。
    """
    from app.gong_ju import deepseek_api
    global _shi_bai_ming
    yuan = os.path.basename(abs_p)
    xin = deepseek_api.gui_fan_ming_jian_yi(yuan, wen_ben, os.path.dirname(rel))
    if not xin:
        return rel, abs_p
    # 统一规范：扩展名、8 位日期前缀、空主题兜底（公共函数，收件箱归档也用）
    xin = ming_ming_gui_ze.gui_fan_hua_ming(abs_p, xin)
    if xin == yuan:
        return rel, abs_p
    mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(os.path.dirname(abs_p), xin)
    if os.path.abspath(mu_biao) == os.path.abspath(abs_p):
        return rel, abs_p
    # 带重试的改名：WPS/杀毒/索引器短暂占用时自动等一等（原文件已用副本提取，通常不会锁）
    ok, err = wen_jian_cao_zuo.gai_ming(abs_p, mu_biao)
    if not ok:
        _shi_bai_ming += 1
        _ji_shi_bai("改名失败", abs_p, str(err))
        print(f"[AI改名失败] {yuan}: {err}")
        return rel, abs_p
    return os.path.relpath(mu_biao, config.WEN_DANG_KU), mu_biao


def wen_jian_suo_yin(yi_ge_wen_jian, ai_ming: bool = False, qiang_zhi: bool = False):
    """索引单个文件：入库 + 文件级向量 + 分块向量。返回 'xin_zeng'/'tiao_guo'/'cuo_wu'。

    ai_ming=True 时先用 AI 统一规范文件名（全量重建的可选步骤），再按新路径建索引。
    qiang_zhi=True 时忽略"文件没变化"的跳过判断（补元数据/重建分块时用）。
    """
    rel, abs_p = yi_ge_wen_jian
    try:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(abs_p)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "cuo_wu"

    db = Session()
    try:
        ji_lu = db.query(WenJian).filter_by(lu_jing=rel).first()
        # 文件没变化、且有文件级向量 + 分块向量 -> 跳过
        # （老版本索引没有分块，you_fen_kuai=0 的会被补一次；
        #   文种/年份为空的也补一次，保证元数据齐全）
        if (not qiang_zhi and ji_lu and ji_lu.wen_jian_mtime == mtime
                and ji_lu.you_xiang_liang == 1
                and getattr(ji_lu, "you_fen_kuai", 0) == 1
                and (ji_lu.wen_zhong or "")):
            return "tiao_guo"

        # 索引阶段多提内容（上限 2 万字），老格式按配置走 WPS COM
        wen_ben = wen_jian_ti_qu.ti_qu_wen_ben(
            abs_p, zi_shu_shang_xian=20000,
            yun_xu_com=getattr(config, "SUO_YIN_LAO_GESHI_COM", True))

        # 可选：AI 统一规范文件名（只对能读出内容的文件；图片/视频等保持原名）
        if ai_ming and wen_ben.strip():
            jiu_rel, jiu_abs = rel, abs_p
            xin_rel, xin_abs = _ai_gui_fan_ming(rel, abs_p, wen_ben)
            if xin_abs != jiu_abs:
                rel, abs_p = xin_rel, xin_abs
                try:
                    mtime = datetime.datetime.fromtimestamp(
                        os.path.getmtime(abs_p)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                if ji_lu is not None:
                    # 目标路径若有残留记录先删，避免唯一键冲突
                    chong = db.query(WenJian).filter(
                        (WenJian.lu_jing == rel)
                        | (WenJian.lu_jing == rel.replace(os.sep, "/"))).first()
                    if chong is not None and chong is not ji_lu:
                        db.delete(chong)
                    ji_lu.lu_jing = rel
                    ji_lu.wen_jian_ming = os.path.basename(abs_p)
                    ji_lu.fen_lei = os.path.dirname(rel)
                db.add(GuiDangJiLu(yuan_lu_jing=jiu_abs, xin_lu_jing=abs_p))
                try:
                    xiang_liang_ku.shan_chu_wen_dang(jiu_rel)
                except Exception:
                    pass

        # 向量化的文本 = 位置线索 + 其他归口 + 文件名 + 标签 + 内容。
        # 标签在扁平化存储里替代目录承载分类信息，必须进向量；
        # 提不出文本的文件（图片/视频等）也有"文件名+标签"向量，保证都能被语义搜索命中。
        mian_bao = os.path.splitext(rel)[0].replace(os.sep, " / ")
        gui_kou_xin_xi = ""
        if ji_lu and ji_lu.qi_ta_gui_kou:
            gui_kou_xin_xi = "\n其他归口：" + ji_lu.qi_ta_gui_kou.replace(";", "；")
        biao_qian_xin_xi = ""
        if ji_lu and ji_lu.biao_qian:
            biao_qian_xin_xi = "\n标签：" + ji_lu.biao_qian.replace(",", "，")
        xiang_liang_ku.tian_jia_wen_dang(
            rel, f"位置：{mian_bao}{gui_kou_xin_xi}{biao_qian_xin_xi}\n文件名：{os.path.basename(rel)}\n内容：{wen_ben}",
            {"wen_jian_ming": os.path.basename(rel), "lu_jing": rel})
        you_xiang_liang = 1

        # 文种/年份：为空时用规则补判（规则拿不准的留给 wen_zhong_fu_wu 的 AI 补判）
        wen_zhong = (ji_lu.wen_zhong if ji_lu else "") or ""
        if not wen_zhong:
            lei, xin = wen_zhong_fu_wu.gui_ze_pan_ding(
                os.path.basename(rel), (ji_lu.biao_qian if ji_lu else "") or "",
                (ji_lu.zhai_yao if ji_lu else "") or "", os.path.splitext(rel)[1].lower())
            if lei and xin == "高":
                wen_zhong = lei
        nian_fen = ((ji_lu.nian_fen if ji_lu else 0)
                    or wen_zhong_fu_wu.nian_fen_cong(os.path.basename(rel), abs_p))

        # 分块向量：正文切块（规章按"第X条"切；同路径会先删旧块再写）
        dang_qian_bq = (ji_lu.biao_qian if ji_lu else "") or ""
        kuai_lie = _qie_kuai(wen_ben, gui_zhang=("规章制度" in dang_qian_bq
                                                or wen_zhong == "规章制度"))
        xiang_liang_ku.tian_jia_fen_kuai(rel, os.path.basename(rel), kuai_lie,
                                         wen_zhong=wen_zhong)
        you_fen_kuai = 1

        if ji_lu:
            ji_lu.wen_jian_mtime = mtime
            ji_lu.you_xiang_liang = you_xiang_liang
            ji_lu.you_fen_kuai = you_fen_kuai
            ji_lu.wen_zhong = wen_zhong
            ji_lu.nian_fen = nian_fen
            ji_lu.fen_lei = os.path.dirname(rel)
            ji_lu.geng_xin_shi_jian = datetime.datetime.now()
        else:
            db.add(WenJian(
                lu_jing=rel, wen_jian_ming=os.path.basename(rel),
                fen_lei=os.path.dirname(rel), wen_jian_mtime=mtime,
                wen_zhong=wen_zhong, nian_fen=nian_fen,
                you_xiang_liang=you_xiang_liang, you_fen_kuai=you_fen_kuai))
        db.commit()
        return "xin_zeng" if you_xiang_liang else "tiao_guo"
    except Exception as e:
        db.rollback()
        print(f"[索引失败] {rel}: {e}")
        return "cuo_wu"
    finally:
        db.close()


def zhi_xing_suo_yin(ai_ming: bool = False):
    """完整跑一轮增量索引。在线程里调用。"""
    global _shi_bai_ming
    _shi_bai_ming = 0
    jin_du.update(yun_xing_zhong=True, wan_cheng=0, xin_zeng=0, tiao_guo=0, cuo_wu=0,
                  gai_ming_shi_bai=0, zui_hou_xin_xi="正在扫描文件列表…")
    lie_biao = sao_miao_lie_biao()
    jin_du["zong_shu"] = len(lie_biao)
    for i, wf in enumerate(lie_biao, 1):
        jie_guo = wen_jian_suo_yin(wf, ai_ming=ai_ming)
        jin_du[jie_guo if jie_guo in ("xin_zeng", "tiao_guo", "cuo_wu") else "cuo_wu"] += 1
        jin_du["gai_ming_shi_bai"] = _shi_bai_ming
        jin_du["wan_cheng"] = i
        jin_du["zui_hou_xin_xi"] = f"[{i}/{len(lie_biao)}] {os.path.basename(wf[0])}"
    # 索引完把同名旧版自动作废（幂等，只查规章表，很快）
    try:
        wen_zhong_fu_wu.zi_dong_zuo_fei_jiu_ban()
    except Exception as e:
        print(f"[索引] 自动作废旧版失败（不影响索引）: {e}")
    jin_du["yun_xing_zhong"] = False
    jie_shu = f"完成：新增向量{jin_du['xin_zeng']}，跳过{jin_du['tiao_guo']}，失败{jin_du['cuo_wu']}"
    if _shi_bai_ming:
        jie_shu += f"，改名失败{_shi_bai_ming}（明细见 ri_zhi/chong_jian_shi_bai.log）"
    jin_du["zui_hou_xin_xi"] = jie_shu


def hou_tai_suo_yin(ai_ming: bool = False):
    """启动后台索引线程（如果已有任务在跑则不重复启动）"""
    if jin_du["yun_xing_zhong"]:
        return False
    t = threading.Thread(target=zhi_xing_suo_yin, args=(ai_ming,), daemon=True)
    t.start()
    return True


def _chu_li_shou_jian_xiang_zi_dong():
    """全量重建前自动处理收件箱：AI 命名+标签+摘要 → 归档到年份目录。

    归档时不单独触发后台索引（jian_suo_yin=False），交给紧接着的全量重建统一索引。
    返回 (成功数, 失败数)。
    """
    from app.lan_tu.shou_jian_xiang.views import _jian_yi_yi_ge, _gui_dang_yi_ge
    if not os.path.isdir(config.SHOU_JIAN_XIANG):
        return 0, 0
    cheng_gong, shi_bai = 0, 0
    for ming in sorted(os.listdir(config.SHOU_JIAN_XIANG)):
        p = os.path.join(config.SHOU_JIAN_XIANG, ming)
        if not os.path.isfile(p) or ming.startswith("~$"):
            continue
        try:
            jian_yi = _jian_yi_yi_ge(p)
            if not jian_yi.get("ok"):
                shi_bai += 1
                cuo_wu = jian_yi.get("cuo_wu", "分析失败")
                _ji_shi_bai("收件箱分析失败", p, cuo_wu)
                print(f"[收件箱] 跳过 {ming}：{cuo_wu}")
                continue
            ok, jie_guo = _gui_dang_yi_ge(
                p, ming_ming_gui_ze.gui_fan_hua_ming(p, jian_yi["wen_jian_ming"]),
                jian_yi.get("zhai_yao", ""),
                jian_yi.get("biao_qian", ""), jian_suo_yin=False)
            if ok:
                cheng_gong += 1
            else:
                shi_bai += 1
                _ji_shi_bai("收件箱归档失败", p, jie_guo.get("cuo_wu", ""))
                print(f"[收件箱] 归档失败 {ming}：{jie_guo.get('cuo_wu', '')}")
        except Exception as e:
            shi_bai += 1
            _ji_shi_bai("收件箱处理异常", p, str(e))
            print(f"[收件箱] 处理失败 {ming}：{e}")
    print(f"[收件箱] 完成：归档 {cheng_gong}，失败 {shi_bai}")
    return cheng_gong, shi_bai


def chong_jian_suo_yin(chu_li_shou_jian_xiang: bool = False, ai_ming: bool = False):
    """全量重建（后台线程）。

    chu_li_shou_jian_xiang=True：重建前先把收件箱 AI 命名+归档（归档后一起索引）。
    ai_ming=True：重建时用 AI 给每个能读出内容的文件统一规范文件名（会直接改名）。
    """
    if jin_du["yun_xing_zhong"]:
        return False
    threading.Thread(target=_chong_jian_ren_wu,
                     args=(chu_li_shou_jian_xiang, ai_ming), daemon=True).start()
    return True


def _chong_jian_ren_wu(chu_li_shou_jian_xiang: bool, ai_ming: bool):
    """全量重建后台任务：可选处理收件箱 → 清空两层集合 → 重扫重建。"""
    jin_du.update(yun_xing_zhong=True, zong_shu=0, wan_cheng=0, xin_zeng=0,
                  tiao_guo=0, cuo_wu=0,
                  zui_hou_xin_xi=("正在处理收件箱（AI 命名+归档）…"
                                  if chu_li_shou_jian_xiang else "正在清空旧索引…"))
    try:
        if chu_li_shou_jian_xiang:
            _chu_li_shou_jian_xiang_zi_dong()
        xiang_liang_ku.qing_kong_wen_dang_ku()   # 删文件级集合
        xiang_liang_ku.qing_kong_fen_kuai_ku()   # 删分块集合
        db = Session()
        db.query(WenJian).update({WenJian.you_xiang_liang: 0, WenJian.you_fen_kuai: 0})
        db.commit()
        db.close()
    except Exception as e:
        print(f"[重建] 准备阶段失败（继续重建）：{e}")
    zhi_xing_suo_yin(ai_ming=ai_ming)
