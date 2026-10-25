# -*- coding: utf-8 -*-
# ============================================
# 文种 / 年份元数据服务
#
# 目的：把"自由标签"升级出一层受控元数据，供搜索过滤、MCP 路由、统计使用。
#   文种（12 类）：规章制度 / 工作通知 / 通报 / 分析报告 / 工作总结 / 考核信息
#                  / 会议纪要 / 台账 / 申请审批 / 说明材料 / 论文 / 其他
#   年份：文件名开头的 8 位日期（全库都有），没有则取修改时间
#
# 判定顺序：
#   1. 标签精确命中（人/AI 打过"规章制度""工作通知"等，最可信）
#   2. 文件名关键词打分（多关键词取总分最高；分差太小视为不确定）
#   3. 图片/视频等媒体文件 → 其他
#   4. 仍不确定的交给 DeepSeek 批量判（每批 20 个，3 线程并发）
#
# 说明：文种只是查询过滤条件，不参与向量计算；改文种不需要重建索引。
# ============================================

import os
import re
import json
import datetime
import collections

import config
from app.moxing import Session, WenJian
from app.gong_ju import deepseek_api

WEN_ZHONG_LIE = [
    "规章制度", "工作通知", "通报", "分析报告", "工作总结", "考核信息",
    "会议纪要", "台账", "申请审批", "说明材料", "论文", "其他",
]

WEN_ZHONG_SHUO_MING = {
    "规章制度": "办法、规定、细则、制度、标准、条例、规范、章程、规程、守则",
    "工作通知": "通知、安排、部署类文件",
    "通报": "表彰、批评、情况通报",
    "分析报告": "故障分析、调研报告、评估报告、汇报材料",
    "工作总结": "月度/季度/年度总结、工作小结",
    "考核信息": "考核、考评、履职评价、评定结果",
    "会议纪要": "会议纪要、会议记录",
    "台账": "检查记录、登记表、清单、写实、统计表",
    "申请审批": "申请、请示、审批、报批",
    "说明材料": "情况说明、证明材料",
    "论文": "论文、QC 成果、软著、技术文章",
    "其他": "图片、视频、无法归类的资料",
}

# 标签精确映射（标签是人工/AI 打的，权重最高）
_BIAO_QIAN_YING_SHE = {
    "规章制度": "规章制度",
    "工作通知": "工作通知",
    "通报": "通报",
    "故障分析": "分析报告",
    "分析报告": "分析报告",
    "工作小结": "工作总结",
    "工作总结": "工作总结",
    "申请审批": "申请审批",
    "说明类材料": "说明材料",
    "说明材料": "说明材料",
    "固定台账": "台账",
    "论文": "论文",
    # "固定台账"是个筐，很多考核表也被打了这个标签；下面几个标签权重更高
    "履职考核": "考核信息",
    "月度考核": "考核信息",
    "绩效考核": "考核信息",
    "考核信息": "考核信息",
}

# 标签权重：台账类标签只是"表格形态"，不能压过"考核/规章"这类实质文种
_BIAO_QIAN_QUAN_ZHONG = {"固定台账": 6}
_BIAO_QIAN_MO_REN_QUAN = 10

# 文件名关键词 -> 文种（权重表示该词对文种的指向强度）
_MING_CHENG_GUI_ZE = [
    ("会议纪要", r"纪要|会议记录|会议纪录", 8),
    # "标准化/规范化/制度化建设"是工作汇报，不是制度文件，用负向断言排除
    ("规章制度", r"办法|规定|细则|制度(?!化)|标准(?!化)|条例|规范(?!化)|章程|规程|守则", 8),
    ("通报", r"通报|表彰决定|批评决定", 8),
    ("工作通知", r"通知", 7),
    # 考核表/履职考核/考评成绩是"考核信息"，不是台账；但"考评办法/细则"已先被规章制度拦下
    ("考核信息", r"履职|考核表|考评表|考评成绩|考评结果|月度考核|绩效考核|考核评价", 8),
    ("工作总结", r"总结|小结|汇报", 6),
    ("分析报告", r"分析|报告|调研|研究|评估|诊断", 6),
    ("申请审批", r"申请|审批|请示|报批|签报", 6),
    ("说明材料", r"说明|证明材料", 6),
    ("台账", r"台账|写实|记录表|检查表|登记表|清单|明细表|统计表", 6),
    ("论文", r"论文|QC|软著|专利", 7),
]

MEI_TI_KUO_ZHAN = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
                   ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}


def _chai_biao_qian(biao_qian: str) -> list:
    return [t.strip() for t in re.split(r"[,，;；、]", biao_qian or "") if t.strip()]


def gui_ze_pan_ding(ming: str, biao_qian: str = "", zhai_yao: str = "",
                    kuo_zhan: str = ""):
    """规则判文种。返回 (文种, 置信度)；文种为空表示需要 AI。

    置信度：高 = 可直接用；中/低 = 建议交给 AI 复核。
    """
    ming = ming or ""
    biao_qian = biao_qian or ""
    kuo_zhan = (kuo_zhan or "").lower()

    ji = collections.Counter()

    # 1) 标签精确命中
    for t in _chai_biao_qian(biao_qian):
        if t in _BIAO_QIAN_YING_SHE:
            ji[_BIAO_QIAN_YING_SHE[t]] += _BIAO_QIAN_QUAN_ZHONG.get(t, _BIAO_QIAN_MO_REN_QUAN)

    # 2) 文件名关键词
    for lei, zheng, quan in _MING_CHENG_GUI_ZE:
        if re.search(zheng, ming):
            ji[lei] += quan

    if ji:
        pai = ji.most_common()
        zui, fen = pai[0]
        ci_fen = pai[1][1] if len(pai) > 1 else 0
        # 分差 >=2 才算明确；同分/接近的交给 AI
        if fen >= 10 and fen - ci_fen >= 2:
            return zui, "高"
        if fen >= 6 and fen - ci_fen >= 2:
            return zui, "中"
        if fen >= 5 and fen - ci_fen >= 3:
            return zui, "低"
        return "", "低"

    # 3) 图片/视频：没有文字线索时归"其他"
    if kuo_zhan in MEI_TI_KUO_ZHAN:
        return "其他", "高"

    return "", "低"


def nian_fen_cong(ming: str, abs_lu_jing: str = "") -> int:
    """年份：文件名 8 位日期 > 路径里的年份目录 > 文件的修改时间。"""
    m = re.match(r"^(19|20)\d{6}_", ming or "")
    if m:
        return int(ming[:4])
    m = re.search(r"(19|20)\d{2}", os.path.basename(os.path.dirname(abs_lu_jing or "")))
    if m:
        return int(m.group(0))
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(abs_lu_jing)).year
    except Exception:
        return datetime.datetime.now().year


# ---------------- AI 批量判定 ----------------

_AI_TI_SHI = """你是文档分类助手。把每个文件判为下列文种之一（只能选一个）：
规章制度、工作通知、通报、分析报告、工作总结、考核信息、会议纪要、台账、申请审批、说明材料、论文、其他

判定要点：
1. 看"文件名 + 标签 + 摘要"，判断这份文件本身是什么，不是它提到了什么。
2. 文件名同时含"通知"和"办法/规定/细则/制度/条例/规范/章程/规程/守则"的，按"规章制度"（实质内容是制度）。
3. "履职考核表、月度考核表、考评表、考评成绩、绩效考核" -> 考核信息；
   即使它是表格形式、标签里有"固定台账"，也归考核信息（标签只是形态，不是文种）。
4. 检查记录、登记表、清单、写实、统计表（不含考核表） -> 台账。
5. 图片、照片、视频 -> 其他（证件照、申请材料照片也归其他）。
6. 不确定就选"其他"，不要硬猜。

输入是一个 JSON 数组，每项有 id、文件名、标签、摘要。
只输出 JSON：{"结果":[{"id":1,"文种":"规章制度"}]}

输入：
"""


def _ai_pan_ding_pi(pi: list) -> dict:
    """一批（<=20）交给 DeepSeek 判文种，返回 {id: 文种}。失败返回空。"""
    ru = [{"id": x["id"], "文件名": x["ming"], "标签": x.get("biao_qian", "")[:160],
           "摘要": x.get("zhai_yao", "")[:120]} for x in pi]
    try:
        xiang_ying = deepseek_api._qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": _AI_TI_SHI + json.dumps(ru, ensure_ascii=False)}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie = json.loads(xiang_ying.choices[0].message.content)
        jie_guo = {}
        for x in jie.get("结果", []):
            wid = x.get("id")
            lei = (x.get("文种") or "").strip()
            if isinstance(wid, int) and lei in WEN_ZHONG_LIE:
                jie_guo[wid] = lei
        return jie_guo
    except Exception as e:
        print(f"[文种] AI 判定失败: {e}")
        return {}


def _fen_pi(ming_dan: list, pi_da_xiao: int = 20) -> list:
    return [ming_dan[i:i + pi_da_xiao] for i in range(0, len(ming_dan), pi_da_xiao)]


def pan_ding_bu_que(yong_ai: bool = True, zui_da_ai: int = 0,
                    jin_du_huichang=None) -> dict:
    """给"文种为空"的文件补判：先规则，规则不确定的再走 AI。

    zui_da_ai>0 时最多送这么多条给 AI（用于先小批量试效果）。
    返回 {"zong_shu","gui_ze","ai","reng_wei_kong","shi_bai"}。
    """
    db = Session()
    try:
        hang_lie = db.query(WenJian).filter(
            (WenJian.wen_zhong == "") | (WenJian.wen_zhong.is_(None))).all()
        # 先把年份补齐（所有行，幂等）
        for h in db.query(WenJian).filter(
                (WenJian.nian_fen == 0) | (WenJian.nian_fen.is_(None))).all():
            abs_p = os.path.join(config.WEN_DANG_KU, (h.lu_jing or "").replace("\\", os.sep))
            h.nian_fen = nian_fen_cong(h.wen_jian_ming, abs_p)
        db.commit()

        dai_ai = []
        gui_ze_shu = 0
        for h in hang_lie:
            kuo_zhan = os.path.splitext(h.wen_jian_ming or "")[1].lower()
            lei, xin = gui_ze_pan_ding(h.wen_jian_ming, h.biao_qian, h.zhai_yao, kuo_zhan)
            if lei and xin == "高":
                h.wen_zhong = lei
                gui_ze_shu += 1
            else:
                dai_ai.append({"id": h.id, "ming": h.wen_jian_ming or "",
                               "biao_qian": h.biao_qian or "",
                               "zhai_yao": h.zhai_yao or "",
                               "kuo_zhan": kuo_zhan,
                               "_gui_ze": lei})
        db.commit()

        if zui_da_ai > 0:
            dai_ai = dai_ai[:zui_da_ai]

        ai_shu = 0
        shi_bai = 0
        if yong_ai and dai_ai:
            # 规则给了"中/低"答案的，作为 AI 的参考；AI 失败时回退用它
            from concurrent.futures import ThreadPoolExecutor
            pi_lie = _fen_pi(dai_ai, 20)
            jie_guo = {}
            with ThreadPoolExecutor(max_workers=3) as chi:
                wei_lai = [chi.submit(_ai_pan_ding_pi, pi) for pi in pi_lie]
                for i, wl in enumerate(wei_lai, 1):
                    try:
                        jie_guo.update(wl.result())
                    except Exception as e:
                        print(f"[文种] 第 {i} 批失败: {e}")
                    if jin_du_huichang:
                        jin_du_huichang(i, len(pi_lie))
            # 回写
            for x in dai_ai:
                lei = jie_guo.get(x["id"]) or x.get("_gui_ze") or ""
                if lei:
                    hang = db.get(WenJian, x["id"])
                    if hang:
                        hang.wen_zhong = lei
                        ai_shu += 1
                else:
                    shi_bai += 1
            db.commit()

        reng_wei_kong = db.query(WenJian).filter(
            (WenJian.wen_zhong == "") | (WenJian.wen_zhong.is_(None))).count()
        zi_dong_zuo_fei_jiu_ban()
        return {"zong_shu": len(hang_lie), "gui_ze": gui_ze_shu,
                "ai": ai_shu, "reng_wei_kong": reng_wei_kong, "shi_bai": shi_bai}
    finally:
        db.close()


# ---------------- 规章：发文单位 / 有效性 ----------------

_SHU_XING_TI_SHI = """你是铁路车辆段文档管理员。读下面的文件开头/落款，提取两项信息：

1. 发文单位：文件的制发单位（如"示例车辆段""中国铁路示例铁路局集团有限公司"）。
   没有明确写就填 ""，不要猜。
2. 有效性：只按文件自身表述判断：
   - 明确写"本办法/本文件自...起施行/继续有效" -> "有效"
   - 明确写"本办法/本文件废止/失效/停止执行" -> "作废"
   - 只写"原有某某文件同时废止"（废止的是别的文件）-> 仍按"有效"或"未知"
   - 没有任何表述 -> "未知"
只输出 JSON：{"发文单位":"...","有效性":"有效|作废|未知","理由":"一句话"}

【文件名】{ming}
【内容节选】{nei_rong}
"""


def _ai_shu_xing(ming: str, nei_rong: str):
    try:
        ti_shi = (_SHU_XING_TI_SHI
                 .replace("{ming}", ming or "")
                 .replace("{nei_rong}", (nei_rong or "")[:2500]))
        xiang_ying = deepseek_api._qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie = json.loads(xiang_ying.choices[0].message.content)
        dan_wei = (jie.get("发文单位") or "").strip()[:100]
        you_xiao = (jie.get("有效性") or "").strip()
        if you_xiao not in ("有效", "作废", "未知"):
            you_xiao = "未知"
        return dan_wei, you_xiao
    except Exception as e:
        print(f"[规章属性] AI 失败: {e}")
        return "", ""


def bu_quan_gui_zhang_shu_xing(yong_ai: bool = True, qiang_zhi: bool = False,
                                jin_du_huichang=None) -> dict:
    """给"规章制度"补发文单位和有效性（AI 读开头/落款）。

    只处理字段为空的；qiang_zhi=True 时全部重跑。返回统计。
    """
    from app.gong_ju import wen_jian_ti_qu
    from concurrent.futures import ThreadPoolExecutor

    db = Session()
    try:
        cha = db.query(WenJian).filter(WenJian.wen_zhong == "规章制度")
        if not qiang_zhi:
            # 以"有效性为空"作为未处理的标记：AI 返回"未知"也算处理过，
            # 否则发文单位本来就空的文件会被反复调用 AI。
            cha = cha.filter(WenJian.you_xiao == "")
        hang_lie = cha.all()
        ren_wu = [(h.id, h.wen_jian_ming, h.lu_jing) for h in hang_lie]
    finally:
        db.close()

    if not ren_wu:
        return {"zong_shu": 0, "cheng_gong": 0, "shi_bai": 0}

    def _chu_li(x):
        wid, ming, rel = x
        abs_p = os.path.join(config.WEN_DANG_KU, (rel or "").replace("\\", os.sep))
        try:
            wen = wen_jian_ti_qu.ti_qu_wen_ben(
                abs_p, zi_shu_shang_xian=3000,
                yun_xu_com=getattr(config, "SUO_YIN_LAO_GESHI_COM", True))
        except Exception:
            wen = ""
        if not yong_ai:
            return wid, "", ""
        dan_wei, you_xiao = _ai_shu_xing(ming, wen)
        return wid, dan_wei, you_xiao

    cheng_gong = shi_bai = 0
    jie_guo = []
    with ThreadPoolExecutor(max_workers=4) as chi:
        for i, (wid, dan_wei, you_xiao) in enumerate(
                chi.map(_chu_li, ren_wu), 1):
            if you_xiao:
                jie_guo.append((wid, dan_wei, you_xiao))
                cheng_gong += 1
            else:
                shi_bai += 1
            if jin_du_huichang:
                jin_du_huichang(i, len(ren_wu))

    db = Session()
    try:
        for wid, dan_wei, you_xiao in jie_guo:
            h = db.get(WenJian, wid)
            if h:
                if dan_wei:
                    h.fa_wen_dan_wei = dan_wei
                h.you_xiao = you_xiao
        db.commit()
    finally:
        db.close()

    zi_dong_zuo_fei_jiu_ban()
    return {"zong_shu": len(ren_wu), "cheng_gong": cheng_gong, "shi_bai": shi_bai}


def _gui_fan_biao_ti(ming: str) -> str:
    """同名制度归一标题（与检索层保持一致）。"""
    s = re.sub(r"^\d{8}_", "", ming or "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"^附件\d+[_\-]?", "", s)
    s = re.sub(r"[（(](试行|暂行|修订版)[)）]", "", s)
    s = re.sub(r"(重新)?(印发|修订|修改|公布|发布)?(通知|通报)$", "", s)
    s = re.sub(r"(修订版|修改版|试行|暂行)$", "", s)
    s = re.sub(r"_\d+$", "", s)
    return s.strip("_- ")


def _wen_jian_ri_qi(ming: str) -> str:
    m = re.match(r"^(\d{8})_", ming or "")
    return m.group(1) if m else ""


def zi_dong_zuo_fei_jiu_ban() -> dict:
    """同名制度自动作废旧版（幂等，可重复跑）。

    规则：
    - 同名、不同日期：只保留最新日期那份，其余 you_xiao='作废'；
    - 同名、同日期（重复副本）：保留文件名最短/不带 _2 后缀的那份，其余作废；
    - 不同标题的文件不处理（避免误伤仍现行有效的旧制度）。
    """
    db = Session()
    try:
        hang = db.query(WenJian).filter(WenJian.wen_zhong == "规章制度").all()
        zu = {}
        for h in hang:
            zu.setdefault(_gui_fan_biao_ti(h.wen_jian_ming), []).append(h)

        zuo_fei = 0
        for biao_ti, lie in zu.items():
            if len(lie) <= 1:
                continue
            zui_da = max(_wen_jian_ri_qi(h.wen_jian_ming) for h in lie)
            zui_xin_lie = [h for h in lie
                           if _wen_jian_ri_qi(h.wen_jian_ming) == zui_da]
            # 同日期的重复副本：优先保留不带 _2/_3 的、文件名短的
            zui_xin_lie.sort(key=lambda h: (
                bool(re.search(r"_\d+(?=\.[^.]+$)", h.wen_jian_ming or "")),
                len(h.wen_jian_ming or "")))
            bao_liu = zui_xin_lie[0]
            for h in lie:
                if h is bao_liu:
                    continue
                if h.you_xiao != "作废":
                    h.you_xiao = "作废"
                    zuo_fei += 1
        db.commit()
        return {"zuo_fei": zuo_fei, "zu": len(zu), "zong_shu": len(hang)}
    finally:
        db.close()


def tong_ji() -> dict:
    """文种分布 + 覆盖情况。"""
    from sqlalchemy import func
    db = Session()
    try:
        hang = db.query(WenJian.wen_zhong, func.count()).group_by(WenJian.wen_zhong).all()
        fen_bu = {k or "（空）": v for k, v in hang}
        nian = db.query(WenJian.nian_fen, func.count()).group_by(WenJian.nian_fen).all()
        return {
            "fen_bu": fen_bu,
            "nian_fen": {str(k or 0): v for k, v in nian},
            "zong_shu": sum(fen_bu.values()),
            "wei_pan": fen_bu.get("（空）", 0),
        }
    finally:
        db.close()
