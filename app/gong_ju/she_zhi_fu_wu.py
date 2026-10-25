# -*- coding: utf-8 -*-
# ============================================
# 设置服务：网页端「系统设置」的读取、保存、热生效
#
# 保存位置: shu_ju/she_zhi.json（config.py 启动时会读取它覆盖环境变量/默认值）
# 保存后：
#   - DeepSeek Key/模型/提示词：立即生效
#   - 考核库连接：重置连接池，立即生效
#   - 文档库路径、应用台账库、端口/MCP：写入文件，重启服务后生效
#
# 安全：接口不回显完整密码/Key，只返回打码或"已配置"。
# ============================================

import json
import os

import config
from app.gong_ju import deepseek_api

# 可写入设置文件的键（多余键一律忽略）
_KE_GAI_ZI_DUAN = (
    "WEN_DANG_KU", "DB_LEI_XING", "SQLITE_LU_JING",
    "SQL_SERVER", "SQL_YONG_HU", "SQL_MI_MA", "SQL_SHU_JU_KU",
    "KAO_HE_KAI_QI", "KAO_HE_SQL_SERVER", "KAO_HE_YONG_HU", "KAO_HE_MI_MA",
    "KAO_HE_SHU_JU_KU", "KAO_HE_BIAO",
    "DEEPSEEK_KEY", "DEEPSEEK_URL", "DEEPSEEK_MO_XING",
    "MCP_HTTP_KAI_QI", "MCP_HTTP_DUAN_KOU",
    "FU_WU_DUAN_KOU", "FU_WU_HOST",
    "TI_SHI_MING_MING", "TI_SHI_BIAO_QIAN",
)

# 需要重启服务才生效的字段
_CHONG_QI_ZI_DUAN = {
    "WEN_DANG_KU", "DB_LEI_XING", "SQLITE_LU_JING",
    "SQL_SERVER", "SQL_YONG_HU", "SQL_MI_MA", "SQL_SHU_JU_KU",
    "MCP_HTTP_KAI_QI", "MCP_HTTP_DUAN_KOU",
    "FU_WU_DUAN_KOU", "FU_WU_HOST",
}

KE_XUAN_MO_XING = ["deepseek-chat", "deepseek-reasoner", "deepseek-flash"]


def _da_ma(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "****"
    return key[:3] + "****" + key[-4:]


def _yi_peizhi(zhi) -> bool:
    return bool(zhi)


def _zheng_bool(zhi) -> bool:
    if isinstance(zhi, bool):
        return zhi
    return str(zhi).strip().lower() in ("1", "true", "yes", "on", "是")


def _lai_yuan(key: str) -> str:
    if config.du_qu_ben_di_she_zhi().get(key):
        return "网页设置"
    if os.environ.get(key):
        return "环境变量"
    if getattr(config, key, ""):
        return "代码默认"
    return "未配置"


def _db_miao_shu() -> str:
    if str(config.DB_LEI_XING).lower() in ("sqlite", "sqlite3"):
        return f"SQLite：{config.SQLITE_LU_JING}"
    if not config.SQL_SERVER:
        return "未配置 SQL Server 地址"
    return f"SQL Server：{config.SQL_SERVER} / {config.SQL_SHU_JU_KU}"


def _kao_he_miao_shu() -> str:
    if not config.KAO_HE_KAI_QI:
        return "未启用"
    return (f"SQL Server：{config.KAO_HE_SQL_SERVER} / "
            f"{config.KAO_HE_SHU_JU_KU} / {config.KAO_HE_BIAO}")


def du_qu_she_zhi() -> dict:
    """给网页返回当前生效设置（密码/Key 不回显明文）。"""
    return {
        "wen_dang_ku": config.WEN_DANG_KU,
        "db_lei_xing": config.DB_LEI_XING,
        "sqlite_lu_jing": config.SQLITE_LU_JING,
        "sql_server": config.SQL_SERVER,
        "sql_yong_hu": config.SQL_YONG_HU,
        "sql_mi_ma_da_ma": "****" if config.SQL_MI_MA else "",
        "sql_mi_ma_yi_peizhi": _yi_peizhi(config.SQL_MI_MA),
        "sql_shu_ju_ku": config.SQL_SHU_JU_KU,
        "db_miao_shu": _db_miao_shu(),

        "kao_he_kai_qi": config.KAO_HE_KAI_QI,
        "kao_he_sql_server": config.KAO_HE_SQL_SERVER,
        "kao_he_yong_hu": config.KAO_HE_YONG_HU,
        "kao_he_mi_ma_da_ma": "****" if config.KAO_HE_MI_MA else "",
        "kao_he_mi_ma_yi_peizhi": _yi_peizhi(config.KAO_HE_MI_MA),
        "kao_he_shu_ju_ku": config.KAO_HE_SHU_JU_KU,
        "kao_he_biao": config.KAO_HE_BIAO,
        "kao_he_miao_shu": _kao_he_miao_shu(),

        "deepseek_key_da_ma": _da_ma(config.DEEPSEEK_KEY),
        "deepseek_key_lai_yuan": _lai_yuan("DEEPSEEK_KEY"),
        "deepseek_url": config.DEEPSEEK_URL,
        "deepseek_mo_xing": config.DEEPSEEK_MO_XING,
        "ke_xuan_mo_xing": KE_XUAN_MO_XING,

        "mcp_http_kai_qi": config.MCP_HTTP_KAI_QI,
        "mcp_http_duan_kou": config.MCP_HTTP_DUAN_KOU,
        "fu_wu_duan_kou": config.FU_WU_DUAN_KOU,
        "fu_wu_host": config.FU_WU_HOST,

        "ti_shi_ming_ming": deepseek_api.qu_ming_ming_ti_shi(),
        "ti_shi_biao_qian": deepseek_api.qu_biao_qian_ti_shi(),
        "ti_shi_ming_ming_mo_ren": deepseek_api.MING_MING_TI_SHI_MO_REN,
        "ti_shi_biao_qian_mo_ren": deepseek_api.BIAO_QIAN_TI_SHI_MO_REN,
    }


def _zheng_zheng_shu(path: str) -> str:
    path = (path or "").strip()
    return os.path.abspath(os.path.expanduser(path)) if path else ""


def _bao_cun_wen_jian(she: dict) -> bool:
    try:
        mu = os.path.dirname(config.SHE_ZHI_WEN_JIAN)
        if mu:
            os.makedirs(mu, exist_ok=True)
        with open(config.SHE_ZHI_WEN_JIAN, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in she.items() if k in _KE_GAI_ZI_DUAN},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[设置] 写入失败: {e}")
        return False


def _duan_kou(zhi, ming: str):
    try:
        n = int(zhi)
    except (TypeError, ValueError):
        return None, f"{ming}必须是数字"
    if not (1 <= n <= 65535):
        return None, f"{ming}必须在 1-65535 之间"
    return n, ""


def _bu_tong(key: str, xin) -> bool:
    """比较新值是否和当前生效值不同（用于判断要不要提示重启）。"""
    jiu = getattr(config, key, None)
    if isinstance(jiu, bool):
        return bool(xin) != jiu
    if isinstance(jiu, int):
        try:
            return int(xin) != jiu
        except (TypeError, ValueError):
            return True
    if key in ("WEN_DANG_KU", "SQLITE_LU_JING"):
        return os.path.abspath(str(xin or "")) != os.path.abspath(str(jiu or ""))
    if key == "DB_LEI_XING":
        return str(xin).lower() != str(jiu).lower()
    return str(xin or "") != str(jiu or "")


def bao_cun_she_zhi(**kwargs):
    """保存设置。返回 (ok, 提示语, 是否需要重启, 最新设置)。

    密码/Key 传空 = 不修改；如果当前值来自环境变量且文件里还没有，会顺手写入文件，
    保证下次只靠 she_zhi.json 也能连上。
    """
    she = config.du_qu_ben_di_she_zhi()
    gai = []
    chong_qi = False

    def _wen_ben(key, zhi, biao, chang=500):
        nonlocal chong_qi
        if zhi is None:
            return True, ""
        zhi = str(zhi).strip()
        if not zhi:
            return False, f"{biao}不能为空"
        if len(zhi) > chang:
            return False, f"{biao}过长"
        she[key] = zhi
        gai.append(biao)
        if key in _CHONG_QI_ZI_DUAN:
            chong_qi = True
        return True, ""

    # ---------- 文档库 ----------
    if kwargs.get("wen_dang_ku") is not None:
        p = _zheng_zheng_shu(kwargs.get("wen_dang_ku"))
        if not p:
            return False, "文档库路径不能为空", False, du_qu_she_zhi()
        she["WEN_DANG_KU"] = p
        gai.append("文档库路径")
        chong_qi = True

    # ---------- 应用台账库 ----------
    if kwargs.get("db_lei_xing") is not None:
        lei = str(kwargs.get("db_lei_xing")).strip().lower()
        if lei not in ("sqlite", "mssql"):
            return False, "数据库类型只支持 sqlite / mssql", False, du_qu_she_zhi()
        she["DB_LEI_XING"] = lei
        gai.append("数据库类型")
        chong_qi = True

    lei = str(she.get("DB_LEI_XING", config.DB_LEI_XING)).strip().lower()

    if kwargs.get("sqlite_lu_jing") is not None:
        p = _zheng_zheng_shu(kwargs.get("sqlite_lu_jing"))
        if p:
            she["SQLITE_LU_JING"] = p
            gai.append("SQLite 路径")
            chong_qi = True
        elif lei == "sqlite":
            return False, "SQLite 文件路径不能为空", False, du_qu_she_zhi()

    for jian, key, biao, chang in (
        ("sql_server", "SQL_SERVER", "SQL Server 地址", 200),
        ("sql_yong_hu", "SQL_YONG_HU", "SQL Server 用户名", 100),
        ("sql_shu_ju_ku", "SQL_SHU_JU_KU", "SQL Server 数据库名", 100),
    ):
        if kwargs.get(jian) is not None:
            zhi = str(kwargs.get(jian) or "").strip()
            if not zhi:
                if lei == "mssql":
                    return False, f"{biao}不能为空", False, du_qu_she_zhi()
                continue
            ok, cuo = _wen_ben(key, zhi, biao, chang)
            if not ok:
                return False, cuo, False, du_qu_she_zhi()

    if kwargs.get("sql_mi_ma"):
        she["SQL_MI_MA"] = str(kwargs["sql_mi_ma"]).strip()
        gai.append("SQL Server 密码")
        chong_qi = True
    elif "SQL_MI_MA" not in she and config.SQL_MI_MA:
        # 当前密码来自环境变量/默认值：顺手写进文件，重启后不再依赖环境变量
        she["SQL_MI_MA"] = config.SQL_MI_MA

    # ---------- 考核库 ----------
    if kwargs.get("kao_he_kai_qi") is not None:
        she["KAO_HE_KAI_QI"] = _zheng_bool(kwargs.get("kao_he_kai_qi"))
        gai.append("考核库开关")

    kai_kao_he = bool(she.get("KAO_HE_KAI_QI", config.KAO_HE_KAI_QI))
    for jian, key, biao, chang in (
        ("kao_he_sql_server", "KAO_HE_SQL_SERVER", "考核库地址", 200),
        ("kao_he_yong_hu", "KAO_HE_YONG_HU", "考核库用户名", 100),
        ("kao_he_shu_ju_ku", "KAO_HE_SHU_JU_KU", "考核库数据库名", 100),
        ("kao_he_biao", "KAO_HE_BIAO", "考核表名", 128),
    ):
        if kwargs.get(jian) is not None:
            zhi = str(kwargs.get(jian) or "").strip()
            if not zhi:
                if kai_kao_he:
                    return False, f"{biao}不能为空", False, du_qu_she_zhi()
                continue
            ok, cuo = _wen_ben(key, zhi, biao, chang)
            if not ok:
                return False, cuo, False, du_qu_she_zhi()

    if kwargs.get("kao_he_mi_ma"):
        she["KAO_HE_MI_MA"] = str(kwargs["kao_he_mi_ma"]).strip()
        gai.append("考核库密码")
    elif "KAO_HE_MI_MA" not in she and config.KAO_HE_MI_MA:
        she["KAO_HE_MI_MA"] = config.KAO_HE_MI_MA

    # ---------- DeepSeek ----------
    if kwargs.get("deepseek_key"):
        key = str(kwargs["deepseek_key"]).strip()
        if not key.startswith("sk-") or len(key) < 20:
            return False, "API Key 格式不对（应以 sk- 开头且长度足够）", False, du_qu_she_zhi()
        she["DEEPSEEK_KEY"] = key
        gai.append("DeepSeek Key")
    elif "DEEPSEEK_KEY" not in she and config.DEEPSEEK_KEY:
        she["DEEPSEEK_KEY"] = config.DEEPSEEK_KEY

    if kwargs.get("deepseek_url") is not None:
        url = str(kwargs["deepseek_url"]).strip()
        if not url.startswith(("http://", "https://")):
            return False, "DeepSeek 地址必须以 http:// 或 https:// 开头", False, du_qu_she_zhi()
        she["DEEPSEEK_URL"] = url
        gai.append("DeepSeek 地址")

    if kwargs.get("deepseek_mo_xing") is not None:
        mo = str(kwargs["deepseek_mo_xing"]).strip()
        if not mo or len(mo) > 100:
            return False, "模型名不能为空且不超过 100 字", False, du_qu_she_zhi()
        she["DEEPSEEK_MO_XING"] = mo
        gai.append("DeepSeek 模型")

    # ---------- 服务 / MCP ----------
    if kwargs.get("mcp_http_kai_qi") is not None:
        she["MCP_HTTP_KAI_QI"] = _zheng_bool(kwargs.get("mcp_http_kai_qi"))
        gai.append("MCP 开关")
        chong_qi = True

    if kwargs.get("mcp_http_duan_kou") is not None:
        n, cuo = _duan_kou(kwargs.get("mcp_http_duan_kou"), "MCP 端口")
        if n is None:
            return False, cuo, False, du_qu_she_zhi()
        she["MCP_HTTP_DUAN_KOU"] = n
        gai.append("MCP 端口")
        chong_qi = True

    if kwargs.get("fu_wu_duan_kou") is not None:
        n, cuo = _duan_kou(kwargs.get("fu_wu_duan_kou"), "服务端口")
        if n is None:
            return False, cuo, False, du_qu_she_zhi()
        she["FU_WU_DUAN_KOU"] = n
        gai.append("服务端口")
        chong_qi = True

    if kwargs.get("fu_wu_host") is not None:
        host = str(kwargs["fu_wu_host"]).strip()
        if not host:
            return False, "监听地址不能为空", False, du_qu_she_zhi()
        she["FU_WU_HOST"] = host
        gai.append("监听地址")
        chong_qi = True

    # ---------- 提示词（保持原逻辑） ----------
    if kwargs.get("ti_shi_ming_ming") is not None:
        v = str(kwargs["ti_shi_ming_ming"]).strip()
        if not v or v == deepseek_api.MING_MING_TI_SHI_MO_REN:
            she.pop("TI_SHI_MING_MING", None)
        else:
            she["TI_SHI_MING_MING"] = v
        gai.append("命名提示词")

    if kwargs.get("ti_shi_biao_qian") is not None:
        v = str(kwargs["ti_shi_biao_qian"]).strip()
        if not v or v == deepseek_api.BIAO_QIAN_TI_SHI_MO_REN:
            she.pop("TI_SHI_BIAO_QIAN", None)
        else:
            she["TI_SHI_BIAO_QIAN"] = v
        gai.append("标签提示词")

    if not gai:
        return True, "没有需要修改的内容", False, du_qu_she_zhi()

    # 只有真正改变了重启类字段才提示重启（避免保存一次 DeepSeek 也提示重启）
    if chong_qi:
        chong_qi = any(_bu_tong(k, she[k]) for k in _CHONG_QI_ZI_DUAN if k in she)

    if not _bao_cun_wen_jian(she):
        return False, "写入设置文件失败，请检查 shu_ju 目录权限", False, du_qu_she_zhi()

    # ---------- 热更新 config（不重建应用库引擎；需要重启的已标记） ----------
    for key in _KE_GAI_ZI_DUAN:
        if key in she:
            globals_key = key
            try:
                setattr(config, globals_key, she[key])
            except Exception:
                pass
    if she.get("WEN_DANG_KU"):
        config.WEN_DANG_KU = she["WEN_DANG_KU"]
        config.SHOU_JIAN_XIANG = os.path.join(config.WEN_DANG_KU, "00-收件箱")
        for mu in (config.WEN_DANG_KU, config.SHOU_JIAN_XIANG):
            try:
                os.makedirs(mu, exist_ok=True)
            except Exception:
                pass
    # 应用库 URL 只用于展示；真正切换要重启
    try:
        config.SQL_LIAN_JIE = config.gou_jian_lian_jie()
    except Exception:
        pass
    # 考核库连接池重置，立即生效
    try:
        from app.gong_ju import kao_he_shu_ju
        kao_he_shu_ju._YIN_QING = None
        kao_he_shu_ju._HUAN_CUN = {"shi_jian": 0.0, "hang": []}
    except Exception:
        pass
    # DeepSeek 客户端重置
    try:
        deepseek_api._ke_hu = None
    except Exception:
        pass

    xin_xi = "已保存并生效（" + "、".join(gai) + "）"
    if chong_qi:
        xin_xi += "；其中路径/数据库/端口/MCP 设置需要重启服务后生效"
    return True, xin_xi, chong_qi, du_qu_she_zhi()


def ce_shi_shu_ju_ku(**kwargs):
    """测试数据库连接。返回 (ok, 提示语)。

    参数：lei_xing(sqlite/mssql), sqlite_lu_jing, sql_server, sql_yong_hu,
          sql_mi_ma, sql_shu_ju_ku, biao(可选), kao_he(bool，用考核库当前密码)
    """
    from sqlalchemy import URL, create_engine, text

    lei = str(kwargs.get("lei_xing") or "sqlite").strip().lower()
    try:
        if lei in ("sqlite", "sqlite3"):
            lu_jing = _zheng_zheng_shu(kwargs.get("sqlite_lu_jing") or config.SQLITE_LU_JING)
            if not lu_jing:
                return False, "SQLite 文件路径为空"
            mu = os.path.dirname(lu_jing)
            if mu:
                os.makedirs(mu, exist_ok=True)
            url = URL.create("sqlite", database=lu_jing)
            engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            host = str(kwargs.get("sql_server") or "").strip()
            user = str(kwargs.get("sql_yong_hu") or "").strip()
            ku = str(kwargs.get("sql_shu_ju_ku") or "").strip()
            mi = kwargs.get("sql_mi_ma") or (
                config.KAO_HE_MI_MA if kwargs.get("kao_he") else config.SQL_MI_MA)
            if not host or not user or not ku:
                return False, "SQL Server 地址、用户名、数据库名不能为空"
            url = URL.create(
                "mssql+pyodbc", username=user, password=mi or "", host=host,
                database=ku,
                query={"driver": "ODBC Driver 17 for SQL Server",
                       "TrustServerCertificate": "yes"})
            engine = create_engine(url, connect_args={"timeout": 5}, pool_pre_ping=True)
        try:
            with engine.connect() as cn:
                cn.execute(text("SELECT 1"))
                biao = str(kwargs.get("biao") or "").strip()
                if biao:
                    if lei in ("sqlite", "sqlite3"):
                        cn.execute(text(f'SELECT COUNT(*) FROM "{biao}"'))
                    else:
                        cn.execute(text(f"SELECT COUNT(*) FROM [{biao}]"))
            return True, "连接成功" + ("，表可读取" if kwargs.get("biao") else "")
        finally:
            engine.dispose()
    except Exception as e:
        msg = str(e)
        if "pyodbc" in msg.lower() or "ODBC" in msg:
            msg += "（如需连 SQL Server，请安装 pyodbc 和 ODBC Driver 17）"
        return False, msg[:300]
