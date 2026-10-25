# -*- coding: utf-8 -*-
# ============================================
# 文档库管家 · MCP 服务器（stdio）
#
# 作用：让 Kimi / Claude / Cursor 等支持 MCP 的 AI 应用直接检索本机文档库：
#   搜索资料（语义+关键词，带相关片段）→ 读取原文 → 基于你的资料回答/写作。
#
# 使用前提：先启动文档库管家（python run.py），服务地址见 config.FU_WU_HOST/PORT。
# 配置方法：在 AI 应用的 MCP 设置里新增一个 stdio 服务器：
#   命令: 你的 Python 解释器（虚拟环境里的 python / python.exe）
#   参数: 本文件 mcp_server.py 的绝对路径
# 详见 README.md 和 使用说明.md 的"AI 接入"章节。
# ============================================

import json
import re
import urllib.parse
import urllib.request

import config
from mcp.server.mcpserver import MCPServer

JI_KOU = f"http://127.0.0.1:{config.FU_WU_DUAN_KOU}/api/ai"
mcp = MCPServer("文档库管家")


def _qing_qiu_post(lu_jing: str, can_shu: dict) -> dict:
    """POST 本机接口（条款重排用）。"""
    url = JI_KOU + lu_jing
    data = json.dumps(can_shu, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if config.AI_JIE_KOU_KEY:
        req.add_header("X-API-Key", config.AI_JIE_KOU_KEY)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "cuo_wu": f"连不上文档库管家：{e}"}


def _qing_qiu(lu_jing: str, can_shu: dict = None) -> dict:
    """调用本机文档库的 AI 接口。"""
    url = JI_KOU + lu_jing
    if can_shu:
        url += "?" + urllib.parse.urlencode(can_shu)
    req = urllib.request.Request(url)
    if config.AI_JIE_KOU_KEY:
        req.add_header("X-API-Key", config.AI_JIE_KOU_KEY)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False,
                "cuo_wu": f"连不上文档库管家（请先启动 python run.py）：{e}"}


@mcp.tool(description="在私人文档库中检索资料（语义+关键词混合），只查文档文件。"
                      "返回文件名、文种、标签、摘要和相关原文片段（规章会带命中的条款号）。"
                      "query 用中文自然语言或关键词；limit 为返回条数（1-20）。"
                      "wen_zhong 可按文种限定范围：规章制度/工作通知/通报/分析报告/工作总结/"
                      "考核信息/会议纪要/台账/申请审批/说明材料/论文/其他（空=不限）。"
                      "对照制度查违规时传 wen_zhong='规章制度'；查考核台账请用 query_assessments。")
def search_documents(query: str, limit: int = 10, wen_zhong: str = "") -> str:
    can_shu = {"q": query, "n": max(1, min(int(limit), 20))}
    if wen_zhong:
        can_shu["wen_zhong"] = wen_zhong
    r = _qing_qiu("/sousuo", can_shu)
    if not r.get("ok"):
        return r.get("cuo_wu", "检索失败")
    if not r.get("jie_guo"):
        return "没有找到相关文档。"
    hang = []
    for i, x in enumerate(r["jie_guo"], 1):
        ban = ""
        if x.get("chong_fu_ban_ben"):
            ban = "｜同标题有重复副本，已去重"
        elif (x.get("ban_ben_shu") or 1) > 1:
            if x.get("zui_xin_ban"):
                ban = f"｜同名{x['ban_ben_shu']}版，本文为最新"
            else:
                ban = f"｜⚠旧版（最新{x.get('zui_xin_ri_qi')}）"
        bu_fen = [f"{i}. {x.get('ming', '')}",
                  f"   文种: {x.get('wen_zhong') or '（未判）'}｜年份: {x.get('nian_fen') or '（未知）'}"
                  f"｜发文单位: {x.get('fa_wen_dan_wei') or '（无）'}｜有效性: {x.get('you_xiao') or '（未知）'}"
                  + ban,
                  f"   路径: {x.get('xiang_dui_lu_jing', '')}",
                  f"   标签: {x.get('biao_qian') or '（无）'}",
                  f"   摘要: {x.get('zhai_yao') or '（无）'}"]
        if x.get("tiao_kuan"):
            bu_fen.append(f"   命中条款: {x['tiao_kuan']}")
        if x.get("pian_duan"):
            bu_fen.append(f"   相关片段: {x['pian_duan']}")
        hang.append("\n".join(bu_fen))
    return "\n\n".join(hang)


@mcp.tool(description="读取文档库中某个文件的完整正文（最多2万字）。"
                      "path 用检索结果里的相对路径（如 2026/xxx.docx）。"
                      ".doc/.xls 老格式也能读（会调本机 WPS，约几秒）。")
def read_document(path: str) -> str:
    r = _qing_qiu("/du", {"path": path})
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    return (f"【{r.get('wen_jian_ming', '')}】"
            f"标签：{r.get('biao_qian') or '无'}｜摘要：{r.get('zhai_yao') or '无'}\n"
            f"（正文 {r.get('zi_shu', 0)} 字）\n\n{r.get('wen_ben', '')}")


@mcp.tool(description="列出文档库的标签及文件数量，用来了解库里有什么资料、该用什么词检索。")
def list_tags() -> str:
    r = _qing_qiu("/biao_qian")
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    return "、".join(f"{x['biao_qian']}({x['shu']})" for x in r.get("biao_qian", []))


@mcp.tool(description="列出文档库的文种分布（规章制度/工作通知/分析报告/台账等各多少文件）"
                      "以及年份分布，用来判断该按什么范围检索。")
def list_genres() -> str:
    r = _qing_qiu("/wen_zhong")
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    bu = ["文种分布："]
    for k, v in sorted(r.get("fen_bu", {}).items(), key=lambda x: -x[1]):
        bu.append(f"  {k}：{v}")
    bu.append("年份分布：" + "、".join(f"{k}({v})" for k, v in
                                     sorted(r.get("nian_fen", {}).items(), reverse=True)))
    return "\n".join(bu)


@mcp.tool(description="查看某个文件的元数据（文种、标签、摘要、更新时间）。path 用相对路径或绝对路径。")
def document_info(path: str) -> str:
    r = _qing_qiu("/wen_jian", {"path": path})
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    return json.dumps(r.get("wen_jian", {}), ensure_ascii=False, indent=2)


@mcp.tool(description="列出最近 N 天（默认30）更新过的文档，用于了解近期资料。")
def recent_documents(days: int = 30, limit: int = 20) -> str:
    r = _qing_qiu("/jin_qi", {"days": days, "n": limit})
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    return "\n".join(f"{x['wen_jian_ming']}（{x['lu_jing']}）" for x in r.get("jie_guo", [])) \
        or "没有记录"


# ============================================
# 考核台账（SQL Server 只读）
# 用于：查历史考核、按维度统计、找相似案例，辅助写分析/通报/总结
# ============================================

def _qu_nian(zhi) -> str:
    """容忍 "2026年" / "2026-09" / "2026" 这类写法，取出四位年份。"""
    m = re.search(r"(19|20)\d{2}", str(zhi or ""))
    return m.group(0) if m else ""


def _qu_yue(zhi) -> str:
    """容忍 "9月" / "09" / "9" / "2026-09"，取出 1-12 的月份。"""
    s = str(zhi or "")
    m = re.search(r"(19|20)\d{2}\s*[-/年]\s*(\d{1,2})", s)
    if not m:
        m = re.search(r"(\d{1,2})", s)
    if not m:
        return ""
    yue = int(m.group(m.lastindex))
    return str(yue) if 1 <= yue <= 12 else ""


def _kao_he_guo_lv(keyword="", year="", month="", level="", category="", major="",
                   unit="", team="", inspector="", person="",
                   start_date="", end_date="", important_only=False) -> dict:
    """把工具参数翻译成接口参数（英文名 -> 后端拼音名）。"""
    d = {}
    if keyword:
        d["guan_jian_ci"] = keyword
    nian = _qu_nian(year)
    if nian:
        d["nian_fen"] = nian
    yue = _qu_yue(month)
    if yue:
        d["yue_fen"] = yue
    if level:
        d["ji_bie"] = level
    if category:
        d["tiao_li_da_lei"] = category
    if major:
        d["tiao_li_zhuan_ye"] = major
    if unit:
        d["ze_ren_dan_wei"] = unit
    if team:
        d["ze_ren_ban_zu"] = team
    if inspector:
        d["jian_cha_ren"] = inspector
    if person:
        d["ze_ren_ren"] = person
    if start_date:
        d["qi_shi"] = start_date
    if end_date:
        d["jie_zhi"] = end_date
    if important_only:
        d["zhong_dian"] = "1"
    return d


def _duan(wen, chang=400) -> str:
    wen = (wen or "").replace("\n", " ").strip()
    return wen if len(wen) <= chang else wen[:chang] + "…"


@mcp.tool(description="查询历史考核台账（只读，数据来自安管系统 SQL Server，约1500条）。"
                      "用户问「某月/某年的考核信息、考核数据、考核台账、履职考核、安全检查考核、"
                      "考核多少条、扣款多少」时用本工具，不要用 search_documents（那只查文档文件）。"
                      "按时间筛选请填 year/month（month 写 9 或 9月都行），"
                      "不要把“9月”写进 keyword；keyword 只放问题内容/人名/设备型号等正文词。"
                      "可按级别、条例大类、责任单位/班组、检查人、责任人、日期范围筛选，按检查时间倒序。"
                      "返回每条的问题内容、条例依据、整改措施、责任人及扣款扣分。")
def query_assessments(keyword: str = "", year: str = "", month: str = "",
                      level: str = "", category: str = "", major: str = "",
                      unit: str = "", team: str = "", inspector: str = "",
                      person: str = "", start_date: str = "", end_date: str = "",
                      important_only: bool = False, limit: int = 10) -> str:
    can_shu = _kao_he_guo_lv(keyword, year, month, level, category, major, unit, team,
                             inspector, person, start_date, end_date, important_only)
    can_shu["n"] = max(1, min(int(limit), 50))
    r = _qing_qiu("/kao_he", can_shu)
    if not r.get("ok"):
        return r.get("cuo_wu", "查询失败")
    if not r.get("jie_guo"):
        return "没有符合条件的考核记录。"
    bu = [f"共 {r.get('zong_shu')} 条（数据来源：安管系统考核台账，不是文档文件），"
          f"显示前 {len(r['jie_guo'])} 条："]
    for i, x in enumerate(r["jie_guo"], 1):
        ze_ren = "；".join(
            f"{y.get('姓名', '')}{'（' + y.get('责任等级', '') + '，扣款' + str(y.get('扣款', 0)) + '元）' if y.get('责任等级') else ''}"
            for y in x.get("责任人明细", []))
        bu.append(
            f"{i}. [id={x.get('id')}] {x.get('检查时间')}｜{x.get('级别')}｜"
            f"{x.get('条例大类')} / {x.get('条例条目')}\n"
            f"   责任：{x.get('责任单位所在车间')} {x.get('责任单位所在班组')}｜检查人：{x.get('检查人')}\n"
            f"   问题：{_duan(x.get('检查内容'))}\n"
            f"   整改：{_duan(x.get('整改措施'), 200)}\n"
            f"   依据：{_duan(x.get('对规对标'), 200)}\n"
            f"   责任人：{ze_ren or '（未填）'}｜扣款合计：{x.get('扣款合计')} 元")
    return "\n".join(bu)


@mcp.tool(description="按维度统计考核条数（只读）。用户问「某月考核多少条、各班组/各大类多少条」时用。"
                      "group_by 可选：年份、月份、年月、级别、问题层级、条例大类、条例条目、条例专业、"
                      "责任单位、责任车间、责任班组、检查人、问题来源、状态、劳安问题、十六种违章。"
                      "其余筛选参数同 query_assessments（月份填 month='9'，不要写进 keyword）。")
def assessment_stats(group_by: str = "条例大类", keyword: str = "", year: str = "",
                     month: str = "", level: str = "", category: str = "",
                     major: str = "", unit: str = "", team: str = "",
                     inspector: str = "", person: str = "",
                     start_date: str = "", end_date: str = "") -> str:
    can_shu = _kao_he_guo_lv(keyword, year, month, level, category, major, unit, team,
                             inspector, person, start_date, end_date)
    can_shu["fen_zu"] = group_by
    r = _qing_qiu("/kao_he/tong_ji", can_shu)
    if not r.get("ok"):
        return r.get("cuo_wu", "统计失败")
    hang = [f"{x['zhi'] or '（空）'}：{x['shu']}" for x in r.get("jie_guo", [])]
    return (f"按「{group_by}」统计（安管系统考核台账，共 "
            f"{sum(x['shu'] for x in r.get('jie_guo', []))} 条）：\n" + "\n".join(hang))


@mcp.tool(description="按维度统计考核扣款和扣分（只读，金额从责任人字段解析）。"
                      "group_by 可选：年月、年份、月份、责任单位、责任车间、责任班组、检查人、条例大类。"
                      "用于做班组考核排名、月度趋势、金额汇总。")
def assessment_fines(group_by: str = "年月", keyword: str = "", year: str = "",
                     month: str = "", level: str = "", category: str = "",
                     unit: str = "", team: str = "", inspector: str = "",
                     start_date: str = "", end_date: str = "") -> str:
    can_shu = _kao_he_guo_lv(keyword, year, month, level, category, "", unit, team,
                             inspector, "", start_date, end_date)
    can_shu["fen_zu"] = group_by
    r = _qing_qiu("/kao_he/kou_kuan", can_shu)
    if not r.get("ok"):
        return r.get("cuo_wu", "统计失败")
    hang = [f"{x['zhi'] or '（空）'}：{x['shu']} 条，扣款 {x['kou_kuan']} 元，扣分 {x['kou_fen']}"
            for x in r.get("jie_guo", [])]
    return f"按「{group_by}」统计：\n" + "\n".join(hang)


@mcp.tool(description="列出考核台账里某个维度的可选值及数量（车间、班组、条例大类、条例条目、"
                      "问题来源等），不确定筛选值怎么写时先调它。dimension 为空则返回常用维度。")
def assessment_dimensions(dimension: str = "") -> str:
    r = _qing_qiu("/kao_he/wei_du", {"ming": dimension} if dimension else None)
    if not r.get("ok"):
        return r.get("cuo_wu", "读取失败")
    bu = []
    for ming, lie in r.get("wei_du", {}).items():
        bu.append(f"【{ming}】" + "、".join(f"{x['zhi'] or '（空）'}({x['shu']})" for x in lie))
    return "\n".join(bu) or "没有数据"


@mcp.tool(description="给一段新发现的考核问题描述，从历史台账里找最相似的案例（只读）。"
                      "写考核分析、定性依据、整改措施时，用历史同类案例做参考。")
def find_similar_assessments(description: str, limit: int = 5) -> str:
    r = _qing_qiu("/kao_he/lei_si", {"miao_shu": description,
                                     "n": max(1, min(int(limit), 20))})
    if not r.get("ok"):
        return r.get("cuo_wu", "查询失败")
    if not r.get("jie_guo"):
        return "没有找到相似案例。"
    bu = []
    for i, x in enumerate(r["jie_guo"], 1):
        bu.append(
            f"{i}. 相似度 {x.get('相似度')}｜[id={x.get('id')}] {x.get('检查时间')}｜"
            f"{x.get('条例大类')} / {x.get('条例条目')}\n"
            f"   问题：{_duan(x.get('检查内容'), 300)}\n"
            f"   依据：{_duan(x.get('对规对标'), 200)}\n"
            f"   整改：{_duan(x.get('整改措施'), 200)}")
    return "\n".join(bu)


# ============================================
# 组合工具：规章核对 / 考核案例分析
# 把"检索规章 + 查历史考核 + 统计"串成一次调用，减少 AI 来回试
# ============================================

# 低于这个相关度就认为"没有明确依据"（实测：无关问题约 0.46，真实条款一般 0.59+）
_GUI_ZHANG_YU_ZHI = 0.52


@mcp.tool(description="规章核对：给一段行为/做法（如“作业人员未穿戴防护用品”“故障未及时处置”），"
                      "只从『规章制度』文种里找相关条款原文；同名制度默认只用最新版，旧版会标⚠。"
                      "返回文件名、年份、发文单位、有效性、命中条款和片段，并按直接相关性重排。"
                      "请以原文为依据判断；工具提示『依据不足』时不要硬下结论、不要编造条款。")
def check_compliance(behavior: str, limit: int = 8) -> str:
    # 直接在检索阶段限定文种，避免把台账/分析报告/学习资料当成制度依据
    r = _qing_qiu("/sousuo", {"q": behavior, "n": 20, "wen_zhong": "规章制度"})
    if not r.get("ok"):
        return r.get("cuo_wu", "检索失败")
    jie_guo = r.get("jie_guo", [])
    if not jie_guo:
        return ("没有在规章制度库里检索到相关条款。\n"
                "请确认相关制度是否已入库，或换一种更具体的说法（作业/设备/地点/人员）。")

    zui_gao = jie_guo[0].get("xiang_si_du") or 0
    if zui_gao < _GUI_ZHANG_YU_ZHI:
        return (f"没有找到足够明确的制度条款（最高相关度 {zui_gao:.2f}，低于 "
                f"{_GUI_ZHANG_YU_ZHI:.2f}）。\n现有资料不足以判断是否违规。"
                "建议补充：具体作业/设备/地点、涉及人员、时间，或确认相关制度是否已入库。\n"
                "（为避免误导，本次不列出低相关片段。）")

    # 同名制度只保留最新版；旧版只有在没有新版时才作为参考
    zui_xin_ti = {x.get("biao_ti_gui_fan"): x.get("zui_xin_ri_qi")
                  for x in jie_guo if x.get("zui_xin_ban")}
    jie_guo = [x for x in jie_guo
               if x.get("zui_xin_ban") is not False
               or x.get("biao_ti_gui_fan") not in zui_xin_ti]
    # 已自动作废的旧版不再作为依据
    jie_guo = [x for x in jie_guo if x.get("you_xiao") != "作废"]
    if not jie_guo:
        return ("检索到的制度都已被标记为『作废』（同名旧版自动作废），"
                "没有现行有效的依据。请确认是否已有新版制度，或补充关键词重新检索。")

    # AI 条款重排：取前 10 条让 DeepSeek 按"是否直接规定该行为"排序
    dai_pai = jie_guo[:10]
    chong = _qing_qiu_post("/chong_pai", {
        "q": behavior,
        "items": [{"ming": x.get("ming", ""),
                   "tiao_kuan": x.get("tiao_kuan", ""),
                   "pian_duan": x.get("pian_duan", ""),
                   "nian_fen": x.get("nian_fen"),
                   "fa_wen_dan_wei": x.get("fa_wen_dan_wei", ""),
                   "you_xiao": x.get("you_xiao", ""),
                   "zui_xin_ban": x.get("zui_xin_ban")} for x in dai_pai],
    })
    shun_xu = chong.get("shun_xu") if chong.get("ok") else None
    if isinstance(shun_xu, list):
        if not shun_xu:
            return ("AI 判断召回条款与这个问题没有直接关系（依据不足）。\n"
                    "请补充行为发生的具体场景、设备/地点、涉及人员，或确认相关制度是否已入库。")
        dai_pai = [dai_pai[i] for i in shun_xu if 0 <= i < len(dai_pai)]
    jie_guo = dai_pai[:max(1, min(int(limit), 10))]

    bu = ["以下是从『规章制度』中检索到的条款（已按直接相关性重排）："]
    for i, x in enumerate(jie_guo, 1):
        ban = ""
        if x.get("chong_fu_ban_ben"):
            ban = "｜同标题有重复副本，已去重"
        elif (x.get("ban_ben_shu") or 1) > 1:
            if x.get("zui_xin_ban"):
                ban = f"｜同名{x['ban_ben_shu']}版，本文为最新"
            else:
                ban = f"｜⚠旧版（最新{x.get('zui_xin_ri_qi')}）"
        bu.append(f"{i}. 【{x.get('ming', '')}】"
                  f"{x.get('nian_fen') or '年份未知'}年｜"
                  f"{x.get('fa_wen_dan_wei') or '发文单位未识别'}｜"
                  f"有效性：{x.get('you_xiao') or '未知'}"
                  + (f"｜命中条款：{x['tiao_kuan']}" if x.get("tiao_kuan") else "")
                  + ban + "\n"
                  f"   片段：{_duan(x.get('pian_duan') or x.get('zhai_yao'), 600)}")
    bu.append("提示：以上为检索片段，引用前请核对原文；片段没有明确条款时，不要推断条款号。")
    return "\n".join(bu)


@mcp.tool(description="考核案例分析：输入一条新发现的考核/检查问题描述，自动找历史上最相似的案例、"
                      "同类问题的分布统计、以及可能相关的制度条款。"
                      "用于起草考核分析、问题定性、整改要求和通报。返回的是素材，结论由你判断。")
def analyze_assessment_case(description: str, limit: int = 5) -> str:
    # 1) 相似历史案例
    lei = _qing_qiu("/kao_he/lei_si", {"miao_shu": description,
                                       "n": max(1, min(int(limit), 10))})
    if not lei.get("ok"):
        return lei.get("cuo_wu", "查询失败")
    an_li = lei.get("jie_guo", [])
    bu = []
    if an_li:
        bu.append("【一、相似历史考核案例】")
        for i, x in enumerate(an_li, 1):
            bu.append(f"{i}. 相似度 {x.get('相似度')}｜{x.get('检查时间')}｜"
                      f"{x.get('条例大类')} / {x.get('条例条目')}｜{x.get('级别')}\n"
                      f"   问题：{_duan(x.get('检查内容'), 350)}\n"
                      f"   依据：{_duan(x.get('对规对标'), 250)}\n"
                      f"   整改：{_duan(x.get('整改措施'), 200)}\n"
                      f"   责任人：{', '.join(y.get('姓名', '') for y in x.get('责任人明细', [])) or '未填'}"
                      f"｜扣款：{x.get('扣款合计')} 元")
    else:
        bu.append("【一、相似历史考核案例】没有找到相似案例。")

    # 2) 同类问题分布（用最相似案例的条例大类，看该类问题的条目分布）
    if an_li:
        da_lei = an_li[0].get("条例大类")
        if da_lei:
            tj = _qing_qiu("/kao_he/tong_ji", {"fen_zu": "条例条目", "tiao_li_da_lei": da_lei})
            if tj.get("ok"):
                hang = tj.get("jie_guo", [])[:10]
                bu.append(f"\n【二、同类问题分布（{da_lei}）】")
                bu.append("、".join(f"{x['zhi']}({x['shu']})" for x in hang))

    # 3) 相关制度条款（只在规章制度文种里找）
    gz = _qing_qiu("/sousuo", {"q": description, "n": 15, "wen_zhong": "规章制度"})
    if gz.get("ok"):
        tiao = gz.get("jie_guo", [])[:3]
        if tiao:
            bu.append("\n【三、可能相关的制度条款】")
            for i, x in enumerate(tiao, 1):
                bu.append(f"{i}. 【{x.get('ming', '')}】"
                          + (f"（{x['tiao_kuan']}）" if x.get("tiao_kuan") else "")
                          + f"{_duan(x.get('pian_duan') or x.get('zhai_yao'), 400)}")

    bu.append("\n【四、起草提示】可围绕：问题事实、违反的具体条款、同类问题趋势、"
              "考核定性依据、整改要求、防范措施 展开；引用条款时以原文为准。")
    return "\n".join(bu)


if __name__ == "__main__":
    mcp.run()      # 默认 stdio（由 AI 应用作为子进程拉起）
