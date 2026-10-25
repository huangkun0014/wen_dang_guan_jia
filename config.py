# ============================================
# 文档库管家 - 集中配置
#
# 优先级：代码默认值 < 环境变量 < shu_ju/she_zhi.json（网页设置写入）
# 这样：
#   - 新上传/新部署：不配置也能跑（默认 SQLite + 项目内“文档库”目录）
#   - 本机：shu_ju/she_zhi.json 里保留 SQL Server / 文档库路径 / API Key
#   - 云平台：可以用环境变量注入 PORT / WEN_DANG_KU / DEEPSEEK_KEY 等
#
# 注意：she_zhi.json 含密钥，已在 .gitignore 中排除，不要上传。
# ============================================

import json
import os

XIANG_MU_GEN = os.path.dirname(os.path.abspath(__file__))          # 项目根目录
SHU_JU_MU_LU = os.path.join(XIANG_MU_GEN, "shu_ju")                # 数据目录


def _jia_zai_dotenv():
    """读取项目根目录 .env（不覆盖已有环境变量）。"""
    p = os.path.join(XIANG_MU_GEN, ".env")
    if not os.path.exists(p):
        return
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_jia_zai_dotenv()


def _huan_jing(name: str, default=""):
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def _huan_jing_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "是")


def _huan_jing_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _jue_dui(p) -> str:
    """相对路径按项目根目录解析，避免从别的 cwd 启动时路径跑偏。"""
    p = os.path.expanduser(str(p or ""))
    if not p:
        return p
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(XIANG_MU_GEN, p))


# ---------- 默认值（可被环境变量/设置文件覆盖） ----------
WEN_DANG_KU = _huan_jing("WEN_DANG_KU", os.path.join(XIANG_MU_GEN, "文档库"))

# 应用自己的台账库：默认 SQLite（零依赖）；也可以改成 SQL Server
DB_LEI_XING = _huan_jing("DB_LEI_XING", "sqlite")          # sqlite / mssql
SQLITE_LU_JING = _huan_jing("SQLITE_LU_JING", os.path.join(SHU_JU_MU_LU, "wen_dang_ku.db"))
SQL_SERVER = _huan_jing("SQL_SERVER", "")
SQL_YONG_HU = _huan_jing("SQL_YONG_HU", "")
SQL_MI_MA = _huan_jing("SQL_MI_MA", "")
SQL_SHU_JU_KU = _huan_jing("SQL_SHU_JU_KU", "WenDangKu")

# 考核库（可选，只读）：默认关闭；配置后才启用考核查询
KAO_HE_KAI_QI = _huan_jing_bool("KAO_HE_KAI_QI", False)
KAO_HE_SQL_SERVER = _huan_jing("KAO_HE_SQL_SERVER", SQL_SERVER)
KAO_HE_YONG_HU = _huan_jing("KAO_HE_YONG_HU", SQL_YONG_HU)
KAO_HE_MI_MA = _huan_jing("KAO_HE_MI_MA", SQL_MI_MA)
KAO_HE_SHU_JU_KU = _huan_jing("KAO_HE_SHU_JU_KU", "assessment_db")
KAO_HE_BIAO = _huan_jing("KAO_HE_BIAO", "考核记录")

# DeepSeek（命名/摘要/标签/条款重排）
DEEPSEEK_KEY = _huan_jing("DEEPSEEK_KEY", "")
DEEPSEEK_URL = _huan_jing("DEEPSEEK_URL", "https://api.deepseek.com")
DEEPSEEK_MO_XING = _huan_jing("DEEPSEEK_MO_XING", "deepseek-chat")

# 本地图片识别（LM Studio）
TU_PIAN_SHI_BIE_KAI_GUAN = _huan_jing_bool("TU_PIAN_SHI_BIE_KAI_GUAN", True)
TU_PIAN_SHI_BIE_URL = _huan_jing("TU_PIAN_SHI_BIE_URL", "http://localhost:1234/v1")
TU_PIAN_SHI_BIE_MO_XING = _huan_jing("TU_PIAN_SHI_BIE_MO_XING", "qwen3-vl-8b-instruct")

# 图片识别通道：deepseek（云端） / lm_studio（本地）
TU_PIAN_SHI_BIE_QU_DAO = _huan_jing("TU_PIAN_SHI_BIE_QU_DAO", "deepseek")
DEEPSEEK_SHI_JUE_MO_XING = _huan_jing("DEEPSEEK_SHI_JUE_MO_XING", "deepseek-flash")

# 嵌入模型（本地离线）
QIAN_RU_MO_XING = _huan_jing("QIAN_RU_MO_XING", "BAAI/bge-m3")

# 分块索引
FEN_KUAI_ZI_SHU = _huan_jing_int("FEN_KUAI_ZI_SHU", 450)
FEN_KUAI_CHONG_DIE = _huan_jing_int("FEN_KUAI_CHONG_DIE", 60)
FEN_KUAI_ZUI_DUO = _huan_jing_int("FEN_KUAI_ZUI_DUO", 80)

# 老格式 .doc/.xls：默认只在 Windows 开启（Linux 上没有 WPS COM）
SUO_YIN_LAO_GESHI_COM = _huan_jing_bool("SUO_YIN_LAO_GESHI_COM", os.name == "nt")
LAO_GESHI_COM_KAI_GUAN = _huan_jing_bool("LAO_GESHI_COM_KAI_GUAN", os.name == "nt")

# AI 接入
AI_JIE_KOU_KEY = _huan_jing("AI_JIE_KOU_KEY", "")
MCP_HTTP_KAI_QI = _huan_jing_bool("MCP_HTTP_KAI_QI", True)
MCP_HTTP_DUAN_KOU = _huan_jing_int("MCP_HTTP_DUAN_KOU", 8765)

# 服务
FU_WU_DUAN_KOU = _huan_jing_int("PORT", _huan_jing_int("FU_WU_DUAN_KOU", 8001))
FU_WU_HOST = _huan_jing("FU_WU_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")

# 数据目录
CHROMA_LU_JING = _huan_jing("CHROMA_LU_JING", os.path.join(SHU_JU_MU_LU, "chroma"))
MO_XING_HUAN_CUN = _huan_jing("MO_XING_HUAN_CUN", os.path.join(SHU_JU_MU_LU, "models"))
RI_ZHI_MU_LU = _huan_jing("RI_ZHI_MU_LU", os.path.join(XIANG_MU_GEN, "ri_zhi"))

# 网页设置文件（含密钥，不要上传）
SHE_ZHI_WEN_JIAN = _jue_dui(
    _huan_jing("SHE_ZHI_WEN_JIAN", os.path.join(SHU_JU_MU_LU, "she_zhi.json")))


def du_qu_ben_di_she_zhi() -> dict:
    """读取网页端保存的设置覆盖（文件不存在或坏了返回空）。"""
    try:
        if os.path.exists(SHE_ZHI_WEN_JIAN):
            with open(SHE_ZHI_WEN_JIAN, encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


# ---------- 应用设置文件覆盖（文件 > 环境变量 > 默认值） ----------
_BEN_DI_SHE_ZHI = du_qu_ben_di_she_zhi()


def _qu_she_zhi(key: str, default):
    """按默认值的类型转换设置文件里的值；空值视为未设置。"""
    v = _BEN_DI_SHE_ZHI.get(key)
    if v is None or v == "":
        return default
    if isinstance(default, bool):
        return str(v).strip().lower() in ("1", "true", "yes", "on", "是")
    if isinstance(default, int):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    return str(v)


for _k in (
    "WEN_DANG_KU", "DB_LEI_XING", "SQLITE_LU_JING", "SQL_SERVER",
    "SQL_YONG_HU", "SQL_MI_MA", "SQL_SHU_JU_KU",
    "KAO_HE_KAI_QI", "KAO_HE_SQL_SERVER", "KAO_HE_YONG_HU", "KAO_HE_MI_MA",
    "KAO_HE_SHU_JU_KU", "KAO_HE_BIAO",
    "DEEPSEEK_KEY", "DEEPSEEK_URL", "DEEPSEEK_MO_XING",
    "TU_PIAN_SHI_BIE_KAI_GUAN", "TU_PIAN_SHI_BIE_URL", "TU_PIAN_SHI_BIE_MO_XING",
    "TU_PIAN_SHI_BIE_QU_DAO", "DEEPSEEK_SHI_JUE_MO_XING",
    "QIAN_RU_MO_XING", "FEN_KUAI_ZI_SHU", "FEN_KUAI_CHONG_DIE", "FEN_KUAI_ZUI_DUO",
    "SUO_YIN_LAO_GESHI_COM", "LAO_GESHI_COM_KAI_GUAN",
    "AI_JIE_KOU_KEY", "MCP_HTTP_KAI_QI", "MCP_HTTP_DUAN_KOU",
    "FU_WU_DUAN_KOU", "FU_WU_HOST", "CHROMA_LU_JING", "MO_XING_HUAN_CUN", "RI_ZHI_MU_LU",
):
    globals()[_k] = _qu_she_zhi(_k, globals()[_k])

# 考核库没单独配置时，沿用应用库的服务器/账号（数据库名和表名仍独立）
if "KAO_HE_SQL_SERVER" not in _BEN_DI_SHE_ZHI:
    KAO_HE_SQL_SERVER = SQL_SERVER
if "KAO_HE_YONG_HU" not in _BEN_DI_SHE_ZHI:
    KAO_HE_YONG_HU = SQL_YONG_HU
if "KAO_HE_MI_MA" not in _BEN_DI_SHE_ZHI:
    KAO_HE_MI_MA = SQL_MI_MA

# 派生路径（必须在覆盖之后算；相对路径统一按项目根目录解析）
WEN_DANG_KU = _jue_dui(WEN_DANG_KU)
SQLITE_LU_JING = _jue_dui(SQLITE_LU_JING)
CHROMA_LU_JING = _jue_dui(CHROMA_LU_JING)
MO_XING_HUAN_CUN = _jue_dui(MO_XING_HUAN_CUN)
RI_ZHI_MU_LU = _jue_dui(RI_ZHI_MU_LU)
SHOU_JIAN_XIANG = os.path.join(WEN_DANG_KU, "00-收件箱")


def _que_bao_mu_lu():
    for mu in (WEN_DANG_KU, SHOU_JIAN_XIANG, SHU_JU_MU_LU, CHROMA_LU_JING,
               MO_XING_HUAN_CUN, RI_ZHI_MU_LU):
        try:
            os.makedirs(mu, exist_ok=True)
        except Exception:
            pass


_que_bao_mu_lu()


def gou_jian_lian_jie():
    """应用台账库连接：默认 SQLite，可切 SQL Server。"""
    from sqlalchemy import URL
    if str(DB_LEI_XING).lower() in ("sqlite", "sqlite3"):
        lu_jing = os.path.abspath(SQLITE_LU_JING)
        mu = os.path.dirname(lu_jing)
        if mu:
            try:
                os.makedirs(mu, exist_ok=True)
            except Exception:
                pass
        return URL.create("sqlite", database=lu_jing)
    return URL.create(
        "mssql+pyodbc",
        username=SQL_YONG_HU,
        password=SQL_MI_MA,
        host=SQL_SERVER,
        database=SQL_SHU_JU_KU,
        query={"driver": "ODBC Driver 17 for SQL Server", "TrustServerCertificate": "yes"},
    )


def gou_jian_kao_he_lian_jie():
    """考核库连接（可选，只读）；未启用返回 None。"""
    if not KAO_HE_KAI_QI:
        return None
    from sqlalchemy import URL
    return URL.create(
        "mssql+pyodbc",
        username=KAO_HE_YONG_HU,
        password=KAO_HE_MI_MA,
        host=KAO_HE_SQL_SERVER,
        database=KAO_HE_SHU_JU_KU,
        query={"driver": "ODBC Driver 17 for SQL Server", "TrustServerCertificate": "yes"},
    )


SQL_LIAN_JIE = gou_jian_lian_jie()
