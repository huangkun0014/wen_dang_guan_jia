# -*- coding: utf-8 -*-
# ============================================
# DeepSeek 调用封装：命名建议、分类建议、摘要生成、规范命名审核
# DeepSeek 官方接口兼容 OpenAI 格式，用 openai SDK 调用
# ============================================

import datetime
import json
import os
import re
import config
from openai import OpenAI

# 客户端懒加载：第一次调用时才创建（避免服务启动时网络卡住）
_ke_hu = None


def _qu_ke_hu():
    global _ke_hu
    if _ke_hu is None:
        _ke_hu = OpenAI(api_key=config.DEEPSEEK_KEY, base_url=config.DEEPSEEK_URL)
    return _ke_hu


def jie_kou_lian_tong(chao_shi: int = 6) -> bool:
    """探测 DeepSeek API 是否可用（列模型接口，不做推理、不花 token；首页状态卡用）。"""
    try:
        ke_hu = OpenAI(api_key=config.DEEPSEEK_KEY, base_url=config.DEEPSEEK_URL,
                       timeout=chao_shi)
        ke_hu.models.list()
        return True
    except Exception:
        return False


def _qing_qiu(chong_shi_ci_shu: int = 3, **kwargs):
    """带重试的 chat.completions.create。

    5xx/超时/连接错误重试（服务器偶发抽风，批量跑时常见），4xx 是请求本身的问题直接抛。
    """
    import time as _time
    from openai import APIConnectionError, APIStatusError, APITimeoutError
    for ci_shu in range(chong_shi_ci_shu):
        try:
            return _qu_ke_hu().chat.completions.create(**kwargs)
        except APIStatusError as e:
            if e.status_code >= 500 and ci_shu < chong_shi_ci_shu - 1:
                print(f"[DeepSeek] 服务器 {e.status_code}，{2 * (ci_shu + 1)} 秒后重试…")
                _time.sleep(2 * (ci_shu + 1))
                continue
            raise
        except (APIConnectionError, APITimeoutError):
            if ci_shu < chong_shi_ci_shu - 1:
                print(f"[DeepSeek] 连接超时，{2 * (ci_shu + 1)} 秒后重试…")
                _time.sleep(2 * (ci_shu + 1))
                continue
            raise


# ============================================
# 归档标签参考词库（旧分类目录的扁平化）：新模型下"第一个标签（归口类别）"建议从里面选
BIAO_QIAN_CI_HUI = [
    "工作小结", "固定台账", "工作通知", "故障分析", "工作ppt", "规章制度",
    "申请审批", "说明类材料",
    "软著与QC成果", "论文", "学习资料", "电子书", "个人资料与证件",
    "个人照片", "房产与债权", "生活", "财务与票据",
    "通用PPT", "通用图片", "流程图", "通用视频",
]

# ---------- 可编辑的提示词（网页"提示词设置"可改，存 shu_ju/she_zhi.json） ----------
# 占位符：{jin_tian} 会被替换成今天的日期；{ci_hui} 会被替换成标签参考词库
MING_MING_TI_SHI_MO_REN = """1. 格式：YYYYMMDD_主题.扩展名
2. 日期优先级：文件内容里的日期 > 文件名里的日期 > 今天的日期{jin_tian}
3. 主题公式：单位/对象 + 事项 + 文种（如"示例车间消防通道专项检查记录"），不超过25字
4. 主题要具体：文件名笼统时（如"每日报告""工作汇报""重点信息追踪报告"），必须从内容里提炼出
   具体的事项、问题、地点、结论写进主题，让人看名字就知道这份文件讲了什么；严禁照抄原文件名了事
5. 禁止：不得臆造内容里没有的信息；不要重复日期；个人证件类文件名不得包含完整证件号码"""

BIAO_QIAN_TI_SHI_MO_REN = """标签替代文件夹分类，直接决定文件以后能不能被搜到、归到哪，务必认真给：
1. 共给 4-6 个标签，逗号分隔
2. 第一个标签是"归口类别"，建议从参考词库选：{ci_hui}
   （词库里没有更贴切的，可以按内容自创一个类别）
3. 后面 3-5 个是主题关键词：单位/对象 + 事项 + 关键名词；内容里明确的事项、问题、
   地点、设备名、编号优先作为标签
4. 禁止：不要用"资料、文档、东西、相关"等空泛废词；个人证件类不得含完整证件号码"""


def qu_ming_ming_ti_shi() -> str:
    """取当前的命名规则提示词（网页改过用改的，否则用默认）。"""
    return (config.du_qu_ben_di_she_zhi().get("TI_SHI_MING_MING")
            or MING_MING_TI_SHI_MO_REN)


def qu_biao_qian_ti_shi() -> str:
    """取当前的标签规则提示词（网页改过用改的，否则用默认）。"""
    return (config.du_qu_ben_di_she_zhi().get("TI_SHI_BIAO_QIAN")
            or BIAO_QIAN_TI_SHI_MO_REN)


def _tian_ru(mo_ban: str, jin_tian: str) -> str:
    """把提示词模板里的占位符替换成实际值（没有占位符也不报错）。"""
    return (mo_ban.replace("{jin_tian}", jin_tian)
            .replace("{ci_hui}", "、".join(BIAO_QIAN_CI_HUI)))


def qing_xi_ming(ming: str) -> str:
    """去掉文件名里的非法字符；没扩展名的视为不可信，返回空串。"""
    ming = re.sub(r'[\\/:*?"<>|\r\n]+', "", str(ming)).strip()
    if not os.path.splitext(ming)[1]:
        return ""
    return ming


def zhi_neng_gui_dang(wen_jian_ming: str, nei_rong: str):
    """让 DeepSeek 读文件名+内容，返回 (规范文件名, 摘要, 标签)。

    新模型：不再给"分类目录"，而是给标签（标签替代旧文件夹分类，用于语义检索和归类）。
    返回 None 表示调用失败（网络问题等），调用方应回退到规则命名。
    """
    jin_tian = datetime.datetime.now().strftime("%Y%m%d")
    ti_shi = f"""你是文档管理助手。根据文件名和内容，完成归档决策。

【标签规则】{_tian_ru(qu_biao_qian_ti_shi(), jin_tian)}

【命名规则】{_tian_ru(qu_ming_ming_ti_shi(), jin_tian)}

【输出要求】
1. 摘要：一句话说清这个文件是什么，不超过30字
2. 只输出JSON：{{"wen_jian_ming":"...","zhai_yao":"...","biao_qian":"..."}}

【示例】
输入：文件名"8月消防检查表.xlsx"，内容"动态检查车间2026年8月消防设施专项检查记录，三号库房发现隐患两处…"
输出：{{"wen_jian_ming":"20260831_示例车间8月消防设施专项检查表.xlsx","zhai_yao":"示例车间8月消防设施专项检查记录表","biao_qian":"工作小结,消防,专项检查,隐患,检查记录"}}

【文件名】{wen_jian_ming}
【内容节选】{nei_rong[:2000] if nei_rong else "(无法提取文本；若是图片描述，则这段是对图片内容的文字识别结果)"}"""

    try:
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie_guo = json.loads(xiang_ying.choices[0].message.content)
        # 文件名 sanitize
        ming = qing_xi_ming(jie_guo.get("wen_jian_ming", wen_jian_ming))
        if not ming:
            return None
        # 扩展名强制与原文件一致
        yuan_kzm = os.path.splitext(wen_jian_ming)[1]
        if os.path.splitext(ming)[1].lower() != yuan_kzm.lower():
            ming = os.path.splitext(ming)[0] + yuan_kzm
        jie_guo["wen_jian_ming"] = ming
        jie_guo["zhai_yao"] = (jie_guo.get("zhai_yao") or "")[:200]
        jie_guo["biao_qian"] = (jie_guo.get("biao_qian") or "")[:200]
        jie_guo.pop("fen_lei", None)          # 老字段兜底清掉，避免下游误用
        return jie_guo
    except Exception as e:
        print(f"[DeepSeek] 调用失败: {e}")
        return None


def gui_fan_ming_jian_yi(wen_jian_ming: str, nei_rong: str, suo_zai_mu_lu: str = ""):
    """浏览页"重命名"用的 AI 规范命名：只输出一个标准文件名，不动分类。

    返回规范文件名字符串，失败返回 None（调用方回退到规则命名）。
    """
    jin_tian = datetime.datetime.now().strftime("%Y%m%d")
    kuo_zhan_ming = os.path.splitext(wen_jian_ming)[1]
    ti_shi = f"""你是文档命名规范助手。请给这个文件起一个规范的中文文件名。

【命名规则】
{_tian_ru(qu_ming_ming_ti_shi(), jin_tian)}
- 扩展名必须是 {kuo_zhan_ming}，不要改
- 只输出JSON，格式：{{"wen_jian_ming":"..."}}

【所在目录】{suo_zai_mu_lu or "(未知)"}
【现文件名】{wen_jian_ming}
【内容节选】{nei_rong[:1500] if nei_rong else "(无法提取文本；若是图片描述，则这段是对图片内容的文字识别结果)"}"""

    try:
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie_guo = json.loads(xiang_ying.choices[0].message.content)
        ming = qing_xi_ming(jie_guo.get("wen_jian_ming", ""))
        # 扩展名必须和原来一致，不一致就换掉
        if ming and os.path.splitext(ming)[1].lower() != kuo_zhan_ming.lower():
            ming = os.path.splitext(ming)[0] + kuo_zhan_ming
        return ming or None
    except Exception as e:
        print(f"[DeepSeek] 规范命名失败: {e}")
        return None


def shen_he_biao_qian(wen_jian_ming: str, nei_rong: str, dang_qian_biao_qian: str,
                      ming_wen_ti: str = "", gui_ze_ming: str = ""):
    """标签体检专用：一次调用同时审两件事——
    1. 当前标签是否合适 + 更合适的是什么（不合适时给出完整建议标签）
    2. 文件名是否规范（程序已规则检出 ming_wen_ti；规则改不动时需要 AI 按内容起名）

    返回 {"pan_duan","jian_yi_biao_qian","dong_zuo","li_you","ming_jian_yi"} 或 None。
    dong_zuo 含义：gai_biao_qian=建议替换标签（与当前标签无交集）；
    jia_biao_qian=建议补充标签（与当前标签有关键交集）；bu_dong=保持现状。
    ming_jian_yi=AI起的规范名（不需要AI起名时填空字符串）。
    """
    jin_tian = datetime.datetime.now().strftime("%Y%m%d")
    ci_hui = "、".join(BIAO_QIAN_CI_HUI)

    ming_bu_fen = ""
    if ming_wen_ti:
        if gui_ze_ming:
            ming_yao_qiu = (f"程序规则已能改成：{gui_ze_ming}。若你认为这个主题已能表达内容，ming_jian_yi 填空字符串（程序会自动采用它）；"
                            f"若主题不达意，ming_jian_yi 填你起的更好的名字。")
        else:
            ming_yao_qiu = ("程序规则改不动这个名字（典型：占位名/无语义）。ming_jian_yi 必须填你根据内容起的规范文件名，禁止留空。")
        ming_bu_fen = f"""
【命名审核】程序规则已检出这个文件名的问题是：{ming_wen_ti}
{ming_yao_qiu}
规则：YYYYMMDD_主题.扩展名；主题=单位/对象+事项+文种，不超25字；不得臆造内容里没有的信息；个人证件类不得含完整证件号码"""

    ti_shi = f"""你是文档标签与命名审核员，一次完成两件事：标签审核 + 命名审核。

【标签参考词库】{ci_hui}

【标签规则】标签用于语义搜索和归类：第一个是"归口类别"（建议从词库选），后面是主题关键词。
1. 判断当前标签是否合适：明显与内容不符、或漏了关键标签才算"不合适"（宁可宽松，不要把刚好的改来改去）
2. 不合适时 jian_yi_biao_qian 填**完整的建议标签**（保留当前标签里仍合适的 + 补上缺的），
   程序会看它和当前标签的重合度决定"替换"还是"补充"
3. 合适就直接说合适，jian_yi_biao_qian 填空字符串

【命名规则】
{ming_bu_fen if ming_bu_fen else '文件名程序规则已判定合规，ming_jian_yi 一律填空字符串。'}

【输出JSON】
{{"pan_duan":"合适|不合适","jian_yi_biao_qian":"...","li_you":"一句话理由（30字内）","ming_jian_yi":"规范文件名或空字符串"}}

【当前标签】{dang_qian_biao_qian or "（无标签）"}
【文件名】{wen_jian_ming}
【内容节选】{nei_rong[:1500] if nei_rong else "(无法提取文本，根据文件名判断)"}"""

    try:
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie_guo = json.loads(xiang_ying.choices[0].message.content)
        jian_yi = (jie_guo.get("jian_yi_biao_qian") or "").strip()[:500]
        if jie_guo.get("pan_duan") != "不合适" or not jian_yi:
            jie_guo["pan_duan"] = "合适"
            jie_guo["dong_zuo"] = "bu_dong"
            jie_guo["jian_yi_biao_qian"] = ""
            return jie_guo
        # 建议与当前有关键标签重合 -> 补充；完全无关 -> 替换
        dang_qian_ji = {t.strip() for t in re.split(r"[,，;；、]", dang_qian_biao_qian or "") if t.strip()}
        jian_yi_ji = {t.strip() for t in re.split(r"[,，;；、]", jian_yi) if t.strip()}
        jie_guo["jian_yi_biao_qian"] = jian_yi
        jie_guo["dong_zuo"] = "jia_biao_qian" if (dang_qian_ji & jian_yi_ji) else "gai_biao_qian"
        return jie_guo
    except Exception as e:
        print(f"[DeepSeek] 体检调用失败: {e}")
        return None


def chong_pai_tiao_kuan(behavior: str, items: list) -> list:
    """规章核对用：让 DeepSeek 判断召回的条款和行为的直接相关性，返回 0-based 顺序。

    items: [{"ming","tiao_kuan","pian_duan"}]，最多取前 10 条。
    失败返回空列表（调用方保持原顺序）。
    """
    if not items:
        return []
    items = items[:10]
    lie = []
    for i, x in enumerate(items, 1):
        zui_xin = "是" if x.get("zui_xin_ban") is not False else "否"
        lie.append(f"{i}. {x.get('ming', '')}｜{x.get('tiao_kuan') or '无条款号'}"
                   f"｜{x.get('nian_fen') or '年份未知'}年"
                   f"｜{x.get('fa_wen_dan_wei') or '发文单位未知'}"
                   f"｜有效性：{x.get('you_xiao') or '未知'}"
                   f"｜同名最新版：{zui_xin}"
                   f"｜内容：{(x.get('pian_duan') or '')[:300]}")
    ti_shi = f"""你是铁路规章制度检索助手。用户描述了一个行为/问题，下面是召回的条款。
请判断每条条款与问题的**直接相关性**，从高到低排序。

排序原则：
1. 条款直接规定了该行为/情形（有明确的行为、条件、禁止性规定）排最前；
2. 只是同一主题、但规定的是别的情形，排后面；
3. 完全不相关的不要放进结果；
4. 不要因为出现相同关键词就排前面；
5. 相关度接近时，优先年份新、有效性明确、正式"办法/细则/制度"的文件；
   旧版（同名最新版=否）不要排在新版前面；
6. 综合性的"违章清单"和专项管理办法都相关时，专项办法优先；
   但清单里明确点名了该行为的，可以作为补充保留在结果里。

只输出 JSON：{{"顺序":[3,1,2]}}（填输入编号，只保留相关的）

【问题】{behavior}

【条款】
""" + "\n".join(lie)

    try:
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        jie = json.loads(xiang_ying.choices[0].message.content)
        shun_xu = []
        for x in jie.get("顺序", []):
            try:
                i = int(x) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(items) and i not in shun_xu:
                shun_xu.append(i)
        return shun_xu
    except Exception as e:
        print(f"[DeepSeek] 条款重排失败: {e}")
        return []


def sheng_cheng_zhai_yao(wen_jian_ming: str, nei_rong: str):
    """给已有文件批量生成摘要和标签（索引增强用，失败返回None）。

    返回: {"zhai_yao": "...", "biao_qian": "..."} 或 None
    """
    jin_tian = datetime.datetime.now().strftime("%Y%m%d")
    ti_shi = f"""阅读下面的文件内容，输出JSON：
{{"zhai_yao":"一句话说清这个文件是什么，不超过30字","biao_qian":"4-6个标签,逗号分隔"}}

【标签规则】
{_tian_ru(qu_biao_qian_ti_shi(), jin_tian)}

【文件名】{wen_jian_ming}
【内容】{nei_rong[:2000]}"""
    try:
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_MO_XING,
            messages=[{"role": "user", "content": ti_shi}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return json.loads(xiang_ying.choices[0].message.content)
    except Exception as e:
        print(f"[DeepSeek] 摘要生成失败: {e}")
        return None


# 视觉识别提示词，与 tupian_shibie._TI_SHI 保持一致
_DS_TI_SHI = {
    "ming_ming": (
        "用中文简要描述这张图片，用于给文件起名字。说明：这是什么类型的文件"
        "（发票/证件/截图/照片/表格/图纸等），关键文字内容是什么。"
        "如果是发票或票据，务必读出：抬头、日期、金额。100字以内。"),
    "jie_xi": (
        "用中文详细描述这张图片的内容，用于文档库的语义检索。说明："
        "1. 图片类型（照片/截图/扫描件/票据/证件/图纸/表格等）；"
        "2. 画面里有什么：人物、场景、物体、界面；"
        "3. 能看清的文字内容尽量完整读出（标题、姓名、日期、金额、编号等）；"
        "4. 这张图大概是什么用途。300字以内。"),
}

# DeepSeek 支持的图片格式（官方"图像理解"：JPEG/PNG/GIF/WebP，按文件实际内容判断）
_DS_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".webp": "image/webp"}


def shi_bie_tu_pian(tu_pian_lu_jing: str, yong_tu: str = "jie_xi") -> str:
    """用 DeepSeek 视觉模型识别图片，返回中文描述。失败返回空串。

    大图复用 tupian_shibie 的压缩（最长边2048，绕开超大图问题）；
    bmp 不在官方支持格式里，统一转 PNG 再传。
    """
    import base64
    import io
    try:
        kzm = os.path.splitext(tu_pian_lu_jing)[1].lower()
        # bmp 官方不支持；超大文件（典型：长动画 gif，几十MB）会超 48MB 请求体限制
        # （报 413 HTML 错误页）——这两类统一取首帧转成 JPEG
        if kzm == ".bmp" or os.path.getsize(tu_pian_lu_jing) > 20 * 1024 * 1024:
            from PIL import Image
            img = Image.open(tu_pian_lu_jing)     # gif 默认取首帧，不会整段解码
            img = img.convert("RGB")
            kuan, gao = img.size
            if max(kuan, gao) > 2048:
                bi_li = 2048 / max(kuan, gao)
                img = img.resize((int(kuan * bi_li), int(gao * bi_li)), Image.LANCZOS)
            tu = io.BytesIO()
            img.save(tu, "JPEG", quality=85)
            tu.seek(0)
            mime = "image/jpeg"
        else:
            from app.gong_ju import tupian_shibie      # 延迟导入，避免模块循环
            tu = tupian_shibie._ya_suo_tu_pian(tu_pian_lu_jing)
            if hasattr(tu, "read"):
                mime = "image/jpeg"                      # 压缩后统一 JPEG
            else:
                mime = _DS_MIME.get(kzm, "image/png")
        if hasattr(tu, "read"):
            tu_bian_ma = base64.b64encode(tu.read()).decode("utf-8")
        else:
            with open(tu, "rb") as f:
                tu_bian_ma = base64.b64encode(f.read()).decode("utf-8")
        xiang_ying = _qing_qiu(
            model=config.DEEPSEEK_SHI_JUE_MO_XING,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _DS_TI_SHI.get(yong_tu, _DS_TI_SHI["jie_xi"])},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{tu_bian_ma}"}},
                ],
            }],
            temperature=0.1,
        )
        return (xiang_ying.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[DeepSeek图片识别] 调用失败: {e}")
        return ""
