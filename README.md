# 文档库管家（WenDangKu）

一个可自托管的私人文档库 + 规章检索 + 考核台账查询系统。

把散落的 Word / PDF / 图片 / 表格按年份扁平存放，用 AI 生成摘要和标签，支持
**语义 + 关键词混合检索**、**规章条款核对**、**考核台账查询**，并可通过 MCP 让
Kimi / Claude 等 AI 应用直接查阅。

> 默认零配置：不填任何东西也能用 SQLite 启动；文档库、数据库、DeepSeek Key
> 都可以在首页右上角 **⚙️ 系统设置** 里改。

---

## 功能

- **文档库管理**：收件箱归档、按年份扁平存储、AI 命名、摘要、标签、批量处理。
- **混合检索**：整篇向量 + 段落分块向量 + 关键词，支持按 **文种 / 年份** 过滤。
- **规章核对**：只从「规章制度」文种里找条款，自动标最新版/旧版，条款级重排，支持引用到“第X条/第X章/五、标题”。
- **考核台账**：可选连接 SQL Server 只读查询，按年月/班组/条例大类统计，按扣款排名，找相似历史案例。
- **MCP 接入**：`mcp_server.py` 提供 13 个工具，能被 Kimi Work / Kimi Code / Claude 等调用。
- **可配置**：文档库路径、SQLite/SQL Server、考核库、DeepSeek、MCP/端口都能在网页设置。

---

## 快速开始

### 本机 Python（Windows / Linux / macOS）

要求 Python **3.12**。

```bash
python -m venv huan_jing
# Windows:
huan_jing\Scripts\activate
# Linux/macOS:
source huan_jing/bin/activate

pip install -r requirements.txt
python run.py
```

打开 <http://127.0.0.1:8001>。

- 首次使用语义检索会下载 `bge-m3` ONNX 模型（约 2GB，走 hf-mirror 镜像）。
- Windows 上 `.doc/.xls` 老格式会调用本机 WPS/Word COM；Linux 上自动关闭该功能。

### Docker

```bash
docker compose up -d
```

- 默认端口 `8001`，文档库在 `./data/文档库`，向量/模型/设置在 `./data/shu_ju`。
- 容器内默认 `MCP_HTTP_KAI_QI=false`；需要 MCP 时在 `docker-compose.yml` 打开并映射 8765。
- 模型缓存建议挂载持久化，否则每次重建容器都要重新下载约 2GB。
- 只开 **1 个 worker**（索引线程和 MCP 都是进程内的，多 worker 会重复跑）。

---

## 配置

所有配置都可以在首页右上角 **⚙️ 系统设置** 里改：

| 配置 | 说明 |
| --- | --- |
| 文档库路径 | 默认项目内 `文档库/`；也可以填 `/data/文档库` 等绝对路径 |
| 应用台账库 | 默认 **SQLite**（`shu_ju/wen_dang_ku.db`，零配置）；也可以切 **SQL Server** |
| 考核数据库 | 可选；填 SQL Server 地址/账号/库/表，启用后才有「考核查询」 |
| DeepSeek | API Key、接口地址、模型；不填则 AI 命名/摘要/条款重排不可用 |
| 服务 / MCP | 监听地址、端口、MCP 开关和端口 |

配置优先级：

```
代码默认值  <  环境变量 / .env  <  shu_ju/she_zhi.json（网页设置）
```

- 改文档库路径/数据库/端口/MCP 需要 **重启服务**；改路径/数据库后还要到「索引管理」**全量重建**一次。
- 改 DeepSeek、提示词、考核库连接可热生效。
- `shu_ju/she_zhi.json` 含密钥，已在 `.gitignore` 中排除，**不要提交**。
- 环境变量示例见 `.env.example`；完整字段说明见 [配置说明.md](配置说明.md)。

---

## 数据库说明

### 应用台账库（必须）

默认 SQLite，无需安装数据库。要换 SQL Server：

1. 安装 ODBC Driver 17 for SQL Server 和 `pyodbc`；
2. 在系统设置里选 SQL Server，填地址（如 `127.0.0.1,1433`）、账号、密码、库名；
3. 重启服务，首次会自动建表。

### 考核库（可选，只读）

考核查询依赖一张按固定字段组织的表（默认表名 `考核记录`）。
表名可以在设置里改；如果字段名不同，建议建一个**同名列视图**再填视图名。

关键字段：

`检查时间`、`年份`、`月份`、`级别`、`问题层级`、`条例大类`、`条例条目`、
`条例专业`、`检查内容`、`检查地点`、`检查人`、`责任单位`、`责任单位所在车间`、
`责任单位所在班组`、`整改措施`、`整改情况`、`对规对标`、`条例内容`、
`责任人1`~`责任人4`、`状态`、`考核`、`劳安问题`、`十六种违章`、`问题来源`、`重要`。

没有考核库也不影响文档库功能；考核接口会返回“未启用”的友好提示。

---

## MCP / Kimi 接入

服务启动后，MCP HTTP 入口默认在 `http://127.0.0.1:8765/mcp`（可在设置里关闭/改端口）。

- **Kimi Work**：插件源在 `kimi_work_plugin/`，打包文件 `wendangku_kimi_plugin.zip`。
- **Kimi Code / Claude Desktop / Cursor**：stdio 方式：

```json
{
  "mcpServers": {
    "wendangku": {
      "command": "python",
      "args": ["/绝对路径/mcp_server.py"]
    }
  }
}
```

Windows 下 `command` 填虚拟环境的 `python.exe`。

工具分为三类：

- 文档：`search_documents` / `read_document` / `list_tags` / `list_genres` / `recent_documents` / `document_info`
- 考核：`query_assessments` / `assessment_stats` / `assessment_fines` / `assessment_dimensions` / `find_similar_assessments`
- 组合：`check_compliance`（规章核对）/ `analyze_assessment_case`（考核案例分析）

---

## 目录结构

```
wen_dang_guan_jia/
├── run.py                  # 启动入口
├── config.py               # 配置（默认值/环境变量/she_zhi.json）
├── mcp_server.py           # MCP 服务器
├── app/
│   ├── moxing.py           # 数据模型（SQLite / SQL Server）
│   ├── gong_ju/            # 搜索/索引/向量/提取/考核/设置
│   ├── lan_tu/             # 蓝图（搜索/收件箱/索引/系统/文件/浏览/体检/AI）
│   └── static/index.html   # 前端单页
├── kimi_work_plugin/       # Kimi Work 插件源
├── requirements.txt
├── Dockerfile / docker-compose.yml / Procfile
├── .env.example
├── 配置说明.md
├── 使用说明.md
└── 功能逻辑说明.md
```

---

## 数据与安全

- **不要上传**：`shu_ju/`（向量、模型、`she_zhi.json`）、`ri_zhi/`、`文档库/`、`huan_jing/`、`.env`。
  这些已在 `.gitignore` / `.dockerignore` 中排除。
- 公网部署时，建议：
  - 用反向代理加登录/访问控制；
  - 设置 `AI_JIE_KOU_KEY` 给 `/api/ai/*` 加一道 Key；
  - 不要把 8001 / 8765 直接暴露到公网。
- 系统设置接口不会回显完整密码/Key，但**能修改配置**；公网必须加访问控制。

---

## 常见问题

**Q：启动后搜索没有结果？**
先到「索引管理」点一次“开始增量索引”；首次会下载嵌入模型。

**Q：没有 DeepSeek Key 能用吗？**
能。文档管理、SQLite 台账、关键词搜索可用；AI 命名/摘要/条款重排会提示未配置。

**Q：Linux 上连 SQL Server 报 `pyodbc` 错误？**
安装 `unixodbc-dev` 和 `pyodbc`，并确认有 ODBC Driver 17。

**Q：Windows 上 `.doc/.xls` 读不出正文？**
需要本机安装 WPS 或 Word；并把 `LAO_GESHI_COM_KAI_GUAN` 保持开启。

**Q：考核查询返回“未启用”？**
到系统设置 → 考核数据库，填连接信息并勾选启用，保存后重启（或等待连接池重置）。

更多细节见 [配置说明.md](配置说明.md)、[使用说明.md](使用说明.md) 和 [功能逻辑说明.md](功能逻辑说明.md)。
