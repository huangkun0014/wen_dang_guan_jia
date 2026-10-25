# ============================================
# 数据模型：定义 SQL Server 里的表结构
# 三张表：
#   wen_jian       - 文件索引表（每个文件一行，摘要/标签/向量状态/其他归口）
#   gui_dang_ji_lu  - 归档记录表（谁什么时候从哪归到哪，可追溯）
#   ti_jian_jie_guo - 归类体检结果表（AI审核建议，等人工确认）
# ============================================

from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine, inspect, text, NVARCHAR
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime
import config

Base = declarative_base()

# 注意：所有字符串列必须用 NVARCHAR 而不是默认的 VARCHAR。
# VARCHAR 按 GBK 码页存字符，康熙部首、生僻字等会变成 ?，路径就坏了（2026-09 踩过这个坑）。

# 文件索引表
class WenJian(Base):
    __tablename__ = "wen_jian"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lu_jing = Column(NVARCHAR(500), unique=True, nullable=False)    # 相对文档库的路径，唯一
    wen_jian_ming = Column(NVARCHAR(300), nullable=False)           # 文件名
    fen_lei = Column(NVARCHAR(200), default="")                     # 所在分类（相对路径）
    zhai_yao = Column(NVARCHAR(None), default="")                   # AI生成的一句话摘要（NVARCHAR(MAX)）
    biao_qian = Column(NVARCHAR(500), default="")                   # AI生成的标签，逗号分隔
    qi_ta_gui_kou = Column(NVARCHAR(500), default="")               # 其他归口：;分隔的分类别名，向量检索时同等命中
    wen_zhong = Column(NVARCHAR(20), default="")                    # 文种（受控词表）：规章制度/工作通知/通报/分析报告/工作总结/考核信息/会议纪要/台账/申请审批/说明材料/论文/其他
    nian_fen = Column(Integer, default=0)                           # 年份（文件名8位日期；没有则取修改时间）
    fa_wen_dan_wei = Column(NVARCHAR(100), default="")              # 发文/来源单位（规章、通知用）
    you_xiao = Column(NVARCHAR(10), default="")                     # 有效性：有效/作废/未知（规章用）
    you_xiang_liang = Column(Integer, default=0)                    # 是否已建文件级向量：0否1是
    you_fen_kuai = Column(Integer, default=0)                       # 是否已建分块向量（段落级检索用）：0否1是
    wen_jian_mtime = Column(NVARCHAR(20), default="")               # 文件修改时间(字符串)，增量索引用
    geng_xin_shi_jian = Column(DateTime, default=datetime.datetime.now)

# 归档记录表
class GuiDangJiLu(Base):
    __tablename__ = "gui_dang_ji_lu"
    id = Column(Integer, primary_key=True, autoincrement=True)
    yuan_lu_jing = Column(NVARCHAR(500), nullable=False)            # 归档前完整路径
    xin_lu_jing = Column(NVARCHAR(500), nullable=False)             # 归档后完整路径
    gui_dang_shi_jian = Column(DateTime, default=datetime.datetime.now)

# 归类体检结果表：一轮体检的逐条建议，人工确认后才真正动文件
class TiJianJieGuo(Base):
    __tablename__ = "ti_jian_jie_guo"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lu_jing = Column(NVARCHAR(500), nullable=False)                 # 文件相对路径（体检时快照）
    wen_jian_ming = Column(NVARCHAR(300), nullable=False)
    dang_qian_biao_qian = Column(NVARCHAR(500), default="")         # 体检时的标签快照
    pan_duan = Column(NVARCHAR(20), default="")                     # 合适/不合适
    jian_yi_biao_qian = Column(NVARCHAR(500), default="")           # AI建议的完整标签
    dong_zuo = Column(NVARCHAR(20), default="")                     # 建议动作：gai_biao_qian/jia_biao_qian/bu_dong
    li_you = Column(NVARCHAR(300), default="")                      # 一句话理由
    ming_wen_ti = Column(NVARCHAR(300), default="")                 # 命名问题（规则检出；空=名字合规）
    gui_fan_ming = Column(NVARCHAR(300), default="")                # 建议规范名（AI优先，规则兜底；空=无需改名）
    chu_li_zhuang_tai = Column(NVARCHAR(20), default="待审")         # 待审/已改标签/已加标签/已忽略/已重命名/已失效
    ti_jian_shi_jian = Column(DateTime, default=datetime.datetime.now)

# 全局引擎和会话工厂
_lian_jie_can_shu = {}
if str(config.DB_LEI_XING).lower() in ("sqlite", "sqlite3"):
    # Flask 是多线程的，SQLite 默认禁止跨线程复用连接
    _lian_jie_can_shu["connect_args"] = {"check_same_thread": False}
else:
    _lian_jie_can_shu["pool_pre_ping"] = True
engine = create_engine(config.SQL_LIAN_JIE, **_lian_jie_can_shu)
Session = sessionmaker(bind=engine)

def chu_shi_hua_shu_ju_ku():
    """建表（表已存在则跳过）+ 老库自动补列。服务启动时调用一次。"""
    Base.metadata.create_all(engine)
    # create_all 不会给已存在的表加新列，这里手动补（列名 -> (类型, 默认值SQL)）
    insp = inspect(engine)
    bu_lie = {
        "wen_jian": {
            "qi_ta_gui_kou": ("NVARCHAR(500)", "''"),
            "you_fen_kuai": ("INT", "0"),
            "wen_zhong": ("NVARCHAR(20)", "''"),
            "nian_fen": ("INT", "0"),
            "fa_wen_dan_wei": ("NVARCHAR(100)", "''"),
            "you_xiao": ("NVARCHAR(10)", "''"),
        },
        "ti_jian_jie_guo": {
            "ming_wen_ti": ("NVARCHAR(300)", "''"),
            "gui_fan_ming": ("NVARCHAR(300)", "''"),
            "dang_qian_biao_qian": ("NVARCHAR(500)", "''"),
            "jian_yi_biao_qian": ("NVARCHAR(500)", "''"),
        },
    }
    for biao, lie_dian in bu_lie.items():
        try:
            lie = [c["name"] for c in insp.get_columns(biao)]
            que = [(ming, lei_xing, mo_ren) for ming, (lei_xing, mo_ren) in lie_dian.items()
                   if ming not in lie]
            for ming, lei_xing, mo_ren in que:
                with engine.begin() as lian_jie:
                    lian_jie.execute(text(
                        f"ALTER TABLE {biao} ADD {ming} {lei_xing} NOT NULL DEFAULT {mo_ren}"))
                print(f"[数据库] 已补列 {biao}.{ming}")
        except Exception as e:
            print(f"[数据库] 补列检查失败（不影响运行）: {e}")
