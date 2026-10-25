文档库管家 · Kimi 插件

安装（Kimi Work）：
  左侧「插件」→「个人」页 → 本地安装（或把本 zip 拖入窗口）→ 安装后开【新会话】。
  也可以让内置的 Plugin Builder 导入本目录/压缩包。

使用前提：
  先启动文档库管家（python run.py 或 start.sh），保持运行。
  MCP 地址默认 http://127.0.0.1:8765/mcp，可在首页「系统设置 → 服务/MCP」里改端口或关闭。
  如果 Kimi 提示“文档库连接不可用”，多半是服务重启过：新开一个会话即可。

原理：
  插件通过 URL 连接 MCP，提供 13 个工具：
  - 文档检索：search_documents / read_document / list_tags / list_genres /
    recent_documents / document_info
  - 考核台账（SQL 只读）：query_assessments / assessment_stats / assessment_fines /
    assessment_dimensions / find_similar_assessments
  - 组合：check_compliance（规章核对）/ analyze_assessment_case（考核案例分析）

  问“9月考核信息”时，Kimi 应调用 query_assessments(year=2026, month=9)，
  返回的是安管系统台账（不是文档库里某份“履职考核表”文件）。

如果某个客户端只支持 stdio（不支持 URL）：
  把 kimi.plugin.json 的 mcpServers 改成：
  "wendangku": { "command": "./start_wendangku_mcp.cmd" }
  （同目录已带该启动脚本；Linux/macOS 可用 python mcp_server.py）
