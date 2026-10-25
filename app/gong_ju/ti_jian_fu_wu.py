# -*- coding: utf-8 -*-
# ============================================
# 标签体检服务：批量调 DeepSeek 审核现有文件的标签是否合适 + 文件名是否规范
# 流程：体检（后台逐文件审） -> 人工看报告勾选 -> 批量执行（改标签/加标签/重命名/忽略）
# 执行原则：
#   gai_biao_qian 用建议标签替换现有标签（方向错了）
#   jia_biao_qian 把建议标签合并进现有标签（漏了关键标签）
#   zhong_ming    原地重命名（不动位置）
#   ignore        人工觉得没问题的，标记忽略
# 不移动文件：文件已按年份扁平存放，位置不再代表分类；标签才是分类载体。
# 改标签/加标签都会强制重建该文件的向量（标签在向量文本里，必须重嵌）。
# ============================================

import os
import re
import threading
import time
import config
from app.moxing import Session, WenJian, GuiDangJiLu, TiJianJieGuo
from app.gong_ju import (wen_jian_ti_qu, deepseek_api, xiang_liang_ku,
                         ming_ming_gui_ze, tupian_shibie, wen_jian_cao_zuo)

jin_du = {
    "yun_xing_zhong": False,
    "zong_shu": 0,
    "wan_cheng": 0,
    "gai_biao_qian": 0,    # 建议改标签的条数
    "jia_biao_qian": 0,    # 建议加标签的条数
    "cuo_wu": 0,
    "zui_hou_xin_xi": "",
}


def sao_miao_mu_biao(fan_wei: str):
    """体检范围：空=整个文档库；否则传相对目录如 2025（年份目录）。"""
    lie_biao = []
    gen = os.walk(os.path.join(config.WEN_DANG_KU, fan_wei)) if fan_wei else os.walk(config.WEN_DANG_KU)
    for dp, ds, fs in gen:
        ds[:] = [d for d in ds if not d.startswith("99-") and d != "00-收件箱"]
        for f in fs:
            if f.startswith("~$") or f == "文件索引总表.xlsx" or f.lower().endswith(".lnk"):
                continue
            abs_p = os.path.join(dp, f)
            rel = os.path.relpath(abs_p, config.WEN_DANG_KU)
            lie_biao.append((rel, abs_p))
    return lie_biao


def _he_bing_biao_qian(*lai_yuan: str) -> str:
    """多个标签串合并去重（中英文逗号/分号分隔），最多留10个。"""
    seen, out = set(), []
    for s in lai_yuan:
        for t in re.split(r"[,，;；、]", s or ""):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return ",".join(out[:10])


def zhi_xing_ti_jian(fan_wei: str, zhui_jia: bool = True):
    """完整跑一轮体检（后台线程调用）。结果写 ti_jian_jie_guo 表。

    zhui_jia=True（默认）：追加模式，跳过已体检过的文件，不清空旧结果。
    zhui_jia=False：全量重扫，清空旧结果重新审。
    """
    db = Session()
    if not zhui_jia:
        db.query(TiJianJieGuo).delete()      # 全量模式清空旧结果
        db.commit()                          # 必须提交，否则 close 时回滚
    yi_you = {r.lu_jing for r in db.query(TiJianJieGuo).all()}
    db.close()

    jin_du.update(yun_xing_zhong=True, wan_cheng=0, gai_biao_qian=0, jia_biao_qian=0,
                  cuo_wu=0, zui_hou_xin_xi="正在扫描文件列表…")
    lie_biao = sao_miao_mu_biao(fan_wei)
    if zhui_jia:
        lie_biao = [x for x in lie_biao if x[0] not in yi_you]      # 只审新文件
    jin_du["zong_shu"] = len(lie_biao)

    for i, (rel, abs_p) in enumerate(lie_biao, 1):
        try:
            wen_ben = wen_jian_ti_qu.ti_qu_wen_ben(abs_p, yun_xu_com=True)
            if not wen_ben and os.path.splitext(rel)[1].lower() in \
                    (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"):
                # 与收件箱/重命名同一套流程：图片走视觉识别后再交给 AI 审
                wen_ben = tupian_shibie.shi_bie_tu_pian(abs_p)
            # 命名规则检查（免费、本地）：有问题的把问题清单交给AI一起审，
            # 规则能改的先留着，AI觉得主题不达意会自己起更好的名字
            ming_wen_ti, gui_ze_ming = ming_ming_gui_ze.shen_he_gui_fan(abs_p, os.path.basename(rel))
            # 当前标签快照（数据库里最新状态；没有记录说明还没建过索引，标签为空）
            db2 = Session()
            ji_lu = db2.query(WenJian).filter_by(lu_jing=rel).first()
            dang_qian_biao_qian = ji_lu.biao_qian if ji_lu else ""
            db2.close()
            jie_guo = deepseek_api.shen_he_biao_qian(
                os.path.basename(rel), wen_ben, dang_qian_biao_qian,
                ming_wen_ti="；".join(ming_wen_ti), gui_ze_ming=gui_ze_ming or "")
            if jie_guo:
                # 最终建议名：AI 起了名且能通过规则校验就用AI的，否则用规则名
                zui_zhong_ming = gui_ze_ming or ""
                ai_ming = str(jie_guo.get("ming_jian_yi", "")).strip()
                if ai_ming:
                    _t, ai_gui_fan = ming_ming_gui_ze.shen_he_gui_fan(abs_p, ai_ming)
                    if ai_gui_fan is None:
                        ai_gui_fan = ai_ming          # AI 名本身已合规
                    if ai_gui_fan:
                        zui_zhong_ming = ai_gui_fan
                db = Session()
                db.add(TiJianJieGuo(
                    lu_jing=rel, wen_jian_ming=os.path.basename(rel),
                    dang_qian_biao_qian=dang_qian_biao_qian,
                    pan_duan=jie_guo.get("pan_duan", ""),
                    jian_yi_biao_qian=jie_guo.get("jian_yi_biao_qian", ""),
                    dong_zuo=jie_guo.get("dong_zuo", "bu_dong"),
                    li_you=str(jie_guo.get("li_you", ""))[:300],
                    ming_wen_ti="；".join(ming_wen_ti),
                    gui_fan_ming=zui_zhong_ming))
                db.commit()
                db.close()
                if jie_guo.get("dong_zuo") == "gai_biao_qian":
                    jin_du["gai_biao_qian"] += 1
                elif jie_guo.get("dong_zuo") == "jia_biao_qian":
                    jin_du["jia_biao_qian"] += 1
            else:
                jin_du["cuo_wu"] += 1
        except Exception as e:
            jin_du["cuo_wu"] += 1
            print(f"[体检失败] {rel}: {e}")
        jin_du["wan_cheng"] = i
        jin_du["zui_hou_xin_xi"] = f"[{i}/{len(lie_biao)}] {os.path.basename(rel)}"
        time.sleep(0.3)      # 控制 API 频率

    jin_du["yun_xing_zhong"] = False
    jin_du["zui_hou_xin_xi"] = (f"体检完成：建议改标签 {jin_du['gai_biao_qian']} 个，"
                                f"建议加标签 {jin_du['jia_biao_qian']} 个，失败 {jin_du['cuo_wu']} 个")


def hou_tai_ti_jian(fan_wei: str, zhui_jia: bool = True):
    """启动后台体检线程（已有任务在跑则不重复启动）"""
    if jin_du["yun_xing_zhong"]:
        return False
    threading.Thread(target=zhi_xing_ti_jian, args=(fan_wei, zhui_jia), daemon=True).start()
    return True


def chu_li_ti_jian(dong_zuo: str, ids: list):
    """批量执行体检结论。

    dong_zuo: "gai_biao_qian" 用建议标签替换 / "jia_biao_qian" 建议标签合并进去 /
              "zhong_ming" 原地重命名(不动位置) / "ignore" 忽略
    返回 {ok: 处理成功数, shi_bai: 失败数, tiao_guo: 跳过数}
    """
    db = Session()
    try:
        rows = (db.query(TiJianJieGuo)
                .filter(TiJianJieGuo.id.in_(ids), TiJianJieGuo.chu_li_zhuang_tai == "待审")
                .all())
        chong_jian_ren_wu = []          # 收集需要重建向量的 (rel, abs)
        ok, shi_bai, tiao_guo = 0, 0, 0
        for r in rows:
            abs_p = os.path.join(config.WEN_DANG_KU, r.lu_jing)
            # 动作与条目建议不符的跳过：改标签只处理"建议改标签"的条目；
            # 加标签可处理"建议改标签"和"建议加标签"的条目（用户想把替换改成合并，更安全，合法）
            if dong_zuo == "gai_biao_qian":
                if r.dong_zuo != "gai_biao_qian":
                    tiao_guo += 1
                    continue
            if dong_zuo == "ignore":
                r.chu_li_zhuang_tai = "已忽略"
                ok += 1
                continue
            if dong_zuo == "zhong_ming":
                # 原地重命名：只改文件名，不动位置
                if not r.gui_fan_ming or r.gui_fan_ming == r.wen_jian_ming:
                    r.chu_li_zhuang_tai = "已忽略"      # 没有可改的名
                    ok += 1
                    continue
                if not os.path.isfile(abs_p) or os.path.basename(abs_p) != r.wen_jian_ming:
                    r.chu_li_zhuang_tai = "已失效"      # 文件已被移动/改名/删除
                    shi_bai += 1
                    continue
                mu_lu = os.path.dirname(abs_p)
                mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(mu_lu, r.gui_fan_ming)
                if os.path.exists(mu_biao):      # 兜底：计算后又被占用（同批重复名）再让一次序号
                    mu_biao = ming_ming_gui_ze.bi_kai_chong_ming(mu_lu, os.path.basename(mu_biao))
                try:
                    ok_gm, cuo_wu = wen_jian_cao_zuo.gai_ming(abs_p, mu_biao)
                    if not ok_gm:
                        raise OSError(cuo_wu)
                except Exception as e:
                    r.chu_li_zhuang_tai = "已失效"
                    r.li_you = (r.li_you or "") + f" [重命名失败:{e}]"      # 记录原因，便于排查
                    shi_bai += 1
                    continue
                new_rel = os.path.relpath(mu_biao, config.WEN_DANG_KU)
                try:
                    xiang_liang_ku.shan_chu_wen_dang(r.lu_jing)
                except Exception:
                    pass
                db.query(WenJian).filter_by(lu_jing=r.lu_jing).delete()
                db.add(GuiDangJiLu(yuan_lu_jing=abs_p, xin_lu_jing=mu_biao))
                chong_jian_ren_wu.append((new_rel, mu_biao))
                r.chu_li_zhuang_tai = "已重命名"
                r.gui_fan_ming = os.path.basename(mu_biao)      # 若追加了序号，记录实际落盘名
                ok += 1
                continue
            # ---- 标签类动作：gai_biao_qian / jia_biao_qian ----
            if dong_zuo not in ("gai_biao_qian", "jia_biao_qian") or not r.jian_yi_biao_qian:
                tiao_guo += 1
                continue
            if not os.path.isfile(abs_p) or os.path.basename(abs_p) != r.wen_jian_ming:
                r.chu_li_zhuang_tai = "已失效"      # 文件已被移动/改名/删除
                shi_bai += 1
                continue
            ji_lu = db.query(WenJian).filter_by(lu_jing=r.lu_jing).first()
            if ji_lu is None:
                # 没索引过的文件补一行台账，带上建议标签
                ji_lu = WenJian(lu_jing=r.lu_jing, wen_jian_ming=r.wen_jian_ming,
                                fen_lei=os.path.dirname(r.lu_jing).replace(os.sep, "/"))
                db.add(ji_lu)
            if dong_zuo == "gai_biao_qian":
                # 统一成逗号分隔并去重（AI 偶尔用顿号/分号分隔）
                ji_lu.biao_qian = _he_bing_biao_qian(r.jian_yi_biao_qian)
                r.chu_li_zhuang_tai = "已改标签"
            else:
                ji_lu.biao_qian = _he_bing_biao_qian(ji_lu.biao_qian, r.jian_yi_biao_qian)
                r.chu_li_zhuang_tai = "已加标签"
            ji_lu.you_xiang_liang = 0      # 关键：标签进了向量文本，必须强制重嵌
            chong_jian_ren_wu.append((r.lu_jing, abs_p))
            ok += 1
        db.commit()
    finally:
        db.close()

    # 向量重建放提交后，避免线程读到未提交数据
    for rel, abs_p in chong_jian_ren_wu:
        threading.Thread(
            target=lambda rr=rel, aa=abs_p: __import__(
                "app.gong_ju.suo_yin_fu_wu", fromlist=["wen_jian_suo_yin"]).wen_jian_suo_yin((rr, aa)),
            daemon=True).start()
    return {"ok": ok, "shi_bai": shi_bai, "tiao_guo": tiao_guo}
