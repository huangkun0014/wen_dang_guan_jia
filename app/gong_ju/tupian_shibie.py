# -*- coding: utf-8 -*-
# ============================================
# 图片识别模块（LM Studio 本地视觉模型）
# LM Studio 提供 OpenAI 兼容接口，复用 openai SDK，只换地址。
# 图片转 base64 后发给本机服务，不出内网、不花 API 钱。
# 未启用（config 开关关闭）或调用失败时返回空串，调用方回退到规则命名。
# ============================================

import base64
import os
import urllib.request
import config

# 扩展名 -> data URL 的 MIME 类型（按真实格式声明，识别更准）
MIME_DUI_ZHAO = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
}

# 最近一次识别失败的原因（空串=没失败），供接口返回给前端提示用户
shang_ci_shi_bai_yuan_yin = ""


def lm_studio_zai_xian(chao_shi: int = 3) -> bool:
    """探测 LM Studio 本地服务是否在线（只查模型列表，不做推理，很快）。"""
    try:
        with urllib.request.urlopen(config.TU_PIAN_SHI_BIE_URL + "/models",
                                    timeout=chao_shi) as r:
            return r.status == 200
    except Exception:
        return False


def _ya_suo_tu_pian(tu_pian_lu_jing: str, zui_da_bian: int = 2048):
    """大图先压小再送识别：LM Studio 的视觉引擎对超大图会报 mtmd 错误，
    压缩到最长边 2048 内既绕开报错又加快推理，内容信息足够命名用。
    压缩失败（格式罕见等）就返回原路径，让后续调用自己报错。"""
    try:
        from PIL import Image
        img = Image.open(tu_pian_lu_jing)
        kuan, gao = img.size
        if max(kuan, gao) <= zui_da_bian:
            return tu_pian_lu_jing      # 不大，直接用原图
        bi_li = zui_da_bian / max(kuan, gao)
        img = img.convert("RGB").resize(
            (int(kuan * bi_li), int(gao * bi_li)), Image.LANCZOS)
        import io
        huan_chong = io.BytesIO()
        img.save(huan_chong, "JPEG", quality=85)
        if huan_chong.tell() > 10 * 1024 * 1024:   # 压完还超 10MB 就不折腾了
            return tu_pian_lu_jing
        huan_chong.seek(0)
        return huan_chong
    except Exception:
        return tu_pian_lu_jing


# 两种提示词：命名用（简短要点）/ 解析用（面向语义检索的完整描述）
_TI_SHI = {
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


def shi_bie_tu_pian(tu_pian_lu_jing: str, yong_tu: str = "ming_ming") -> str:
    """识别图片内容，返回一段中文描述。失败返回空串。

    参数:
        yong_tu: "ming_ming"（默认，命名用简短描述）/ "jie_xi"（解析用详细描述）
    失败原因写入模块变量 shang_ci_shi_bai_yuan_yin，调用方可以据此提示用户。
    """
    global shang_ci_shi_bai_yuan_yin
    shang_ci_shi_bai_yuan_yin = ""
    if not config.TU_PIAN_SHI_BIE_KAI_GUAN:
        shang_ci_shi_bai_yuan_yin = "图片识别开关未开启（config.py 的 TU_PIAN_SHI_BIE_KAI_GUAN）"
        return ""
    # 通道切换：deepseek = 云端视觉模型（快，图片按token计费）；
    # lm_studio = 本地服务（免费，CPU上慢）。配置在 config.py 的 TU_PIAN_SHI_BIE_QU_DAO
    if getattr(config, "TU_PIAN_SHI_BIE_QU_DAO", "lm_studio") == "deepseek":
        from app.gong_ju import deepseek_api      # 延迟导入，避免模块循环
        jie_guo = deepseek_api.shi_bie_tu_pian(tu_pian_lu_jing, yong_tu=yong_tu)
        if not jie_guo:
            shang_ci_shi_bai_yuan_yin = "DeepSeek 视觉模型调用失败（网络/余额问题，详见控制台）"
        return jie_guo
    try:
        from openai import OpenAI
        ke_hu = OpenAI(base_url=config.TU_PIAN_SHI_BIE_URL,
                       api_key="lm-studio", timeout=180)   # 视觉模型在 CPU 上推理慢，超时给足
        # 大图先压缩（返回 BytesIO 或原路径），绕过视觉引擎的 mtmd 报错
        tu = _ya_suo_tu_pian(tu_pian_lu_jing)
        if hasattr(tu, "read"):
            tu_bian_ma = base64.b64encode(tu.read()).decode("utf-8")
            mime = "image/jpeg"      # 压缩后统一 JPEG
        else:
            with open(tu, "rb") as f:
                tu_bian_ma = base64.b64encode(f.read()).decode("utf-8")
            mime = MIME_DUI_ZHAO.get(os.path.splitext(tu)[1].lower(), "image/png")
        xiang_ying = ke_hu.chat.completions.create(
            model=config.TU_PIAN_SHI_BIE_MO_XING,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _TI_SHI.get(yong_tu, _TI_SHI["ming_ming"])},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{tu_bian_ma}"}},
                ],
            }],
            temperature=0.1,
        )
        return (xiang_ying.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[图片识别] 调用失败: {e}")
        # 连接失败典型是 LM Studio 没启动服务；把原因记下来给前端提示
        if not lm_studio_zai_xian():
            shang_ci_shi_bai_yuan_yin = "LM Studio 本地服务未启动（打开 LM Studio -> Developer -> Start Server）"
        else:
            shang_ci_shi_bai_yuan_yin = f"视觉模型调用失败：{e}"
        return ""
