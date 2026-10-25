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

### 方式一：本机 Python（Windows / Linux / macOS）

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

### 方式二：Docker

```bash
docker compose up -d
```

- 默认端口 `8001`，文档库在 `./data/文档库`，向量/模型/设置在 `./data/shu_ju`。
- 容器内默认 `MCP_HTTP_KAI_QI=false`；需要 MCP 时在 `docker-compose.yml` 打开并映射 8765。
- 模型缓存建议挂载持久化，否则每次重建容器都要重新下载约 2GB。
- 支持 `Procfile` 的平台会使用 `gunicorn -w 1 --threads 8 run:app`；请只开 **1 个 worker**
  （索引线程和 MCP 都是进程内的，多 worker 会重复跑）。

---

## 首次配置（首页 ⚙️ 系统设置）

| 配置 | 说明 |
| --- | --- |
| 文档库路径 | 默认项目内 `文档库/`；也可以填 `/data/文档库` 等绝对路径 |
| 应用台账库 | 默认 **SQLite**（`shu_ju/wen_dang_ku.db`，零配置）；也可以切 **SQL Server** |
| 考核数据库 | 可选；填 SQL Server 地址/账号/库/表，启用后才有「考核查询」 |
| DeepSeek | API Key、接口地址、模型；不填则 AI 命名/摘要/条款重排不可用 |
| 服务 / MCP | 监听地址、端口、MCP 开关和端口 |

> 文档库路径、数据库、端口、MCP 改完需要 **重启服务**；改路径/数据库后还要到「索引管理」**全量重建**一次。
> DeepSeek 和提示词立即生效。
> 设置保存在 `shu_ju/she_zhi.json`（含密钥，已在 `.gitignore` 中排除，**不要上传**）。

配置优先级：**代码默认值 < 环境变量（含 `.env`） < `shu_ju/she_zhi.json`**。
云平台可以用环境变量注入，见 `.env.example`。

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

工具：`search_documents` / `read_document` / `list_tags` / `list_genres` /
`query_assessments` / `assessment_stats` / `assessment_fines` /
`assessment_dimensions` / `find_similar_assessments` /
`check_compliance` / `analyze_assessment_case` 等。

---

## 打包上传

```bash
python da_bao_shang_chuan.py
```

会生成 `wendangku_release.zip`，只包含代码、文档和部署文件，自动排除
`shu_ju/`（向量/模型/设置）、`ri_zhi/`（日志）、`文档库/`（私人文件）、`huan_jing/`（虚拟环境）
和 `.env`。上传前建议先解压到空目录跑一遍：

```bash
python run.py
```

确认首页、系统设置、索引都能正常打开。

---

## 知乎 AI Works 发布方式

知乎 AI Works 的「上传源码（自动构建）」目前只接受**纯静态前端 / Node.js HTTP 后端 / Node SSR** 项目
（AI Works Skill v1.2.0 的探测分支）。本项目是 **Python Flask**，只读探测结果为：

```json
{
  "Status": "blocked",
  "ProjectType": "unsupported",
  "Findings": [
    {"Code": "E_PROJECT_AMBIGUOUS", "Reason": "No package.json was found at the project root."},
    {"Code": "E_LOCKFILE_MISSING", "Reason": "The isolated delivery source has no npm lockfile yet."}
  ]
}
```

所以**不能直接走「上传源码」**，加一个 `package.json` 也没用——Node 运行时不会执行 Flask。
可选路径：

1. **推荐：站外链接**
   - 用本项目的 `Dockerfile` 把 Python 服务部署到任意公网主机/云托管（VPS、CloudBase 云托管、Railway、Render 等）；
   - 拿到 HTTPS 地址后，在 AI Works 发布方式里选「站外链接」，填这个地址；
   - 这样所有功能（Flask、SQLite/SQL Server、Chroma、MCP）都保留。
2. **CloudBase 云托管/容器**：把 Docker 镜像跑在 CloudBase 的容器服务上，再用「站外链接」。
3. **上传源码**：需要把后端重写成 Node.js（Flask 路由、SQLAlchemy、Chroma、ONNX 嵌入、文档提取都要重做），
   工作量大，不建议为了发布而重写。
4. **GitHub 仓库**：可以展示源码，但平台仍按源码构建规则执行，不会因此支持 Python。

如果只是想在 AI Works 里放一个入口页，也可以上传一个纯静态页，用 iframe/链接指向第 1 步的公网地址；
但真正运行的服务仍在 Python 主机上。

### 公网 Docker 部署（站外链接用）

```bash
unzip wendangku_release.zip
cd wen_dang_guan_jia
cp .env.example .env        # 至少填 DEEPSEEK_KEY；也可部署后在首页设置
docker compose up -d
```

- 文档库和 `shu_ju/` 都挂载在 `./data/`，容器重建不丢；
- 用 Caddy/Nginx 加 HTTPS 和登录，不要把 8001 直接暴露公网；
- 验证 `https://你的域名/api/xi_tong/zhuang_tai` 返回 `shu_ju_ku_ok: true`；
- 然后在 AI Works 选「站外链接」，填这个 HTTPS 地址。

## 公开源码（GitHub / Gitee）

- 仓库只放代码、文档和部署文件；**不要放** `shu_ju/`、`ri_zhi/`、`文档库/`、`huan_jing/`、`.env`、`shu_ju/she_zhi.json`。
- 源码里的单位名、库名、个人示例已替换为通用示例；SQL Server / 考核库 / 本地 AI 的真实配置写在
  [配置说明.md](配置说明.md)，部署时自己填。
- GitHub 经常连不上时：
  - 用 SSH 走 443 端口（`~/.ssh/config`）：
    ```
    Host github.com
      HostName ssh.github.com
      Port 443
      User git
    ```
  - 或者给 `git` 配 HTTPS 代理：
    ```bash
    git config --global http.proxy http://127.0.0.1:你的代理端口
    ```
  - 也可以先推 Gitee，再把 GitHub 当镜像；AI Works 的「GitHub 仓库」只认 GitHub，
    但「站外链接」可以直接指向 Gitee 仓库页。
- AI Works 的「GitHub 仓库」只是项目页的源码入口展示，不会运行 Python；运行仍走「站外链接」。

## 数据与安全

- **不要上传**：`shu_ju/`（向量、模型、`she_zhi.json`）、`ri_zhi/`、`文档库/`、`huan_jing/`、`.env`。
  这些已在 `.gitignore` / `.dockerignore` 中排除。
- 公网部署时，建议：
  - 用反向代理加登录/访问控制；
  - 设置 `AI_JIE_KOU_KEY` 给 `/api/ai/*` 加一道 Key；
  - 不要把 8001 / 8765 直接暴露到公网。
- 系统设置接口不会回显完整密码/Key，但**能修改配置**；公网必须加访问控制。

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
├── da_bao_shang_chuan.py   # 打包上传版（排除数据/密钥）
├── .env.example
├── 配置说明.md
├── 使用说明.md
└── 功能逻辑说明.md
```

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
