@echo off
rem stdio 方式启动 MCP（Kimi Code / Claude Desktop / Cursor 等）
setlocal
set "PY=%~dp0..\huan_jing\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0..\mcp_server.py" %*
