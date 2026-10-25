#!/usr/bin/env bash
# 文档库管家 Linux / macOS 启动脚本
set -e
cd "$(dirname "$0")"

if [ -x "huan_jing/bin/python" ]; then
  PY="huan_jing/bin/python"
elif [ -x "huan_jing/Scripts/python.exe" ]; then
  PY="huan_jing/Scripts/python.exe"
else
  PY="${PYTHON:-python3}"
fi

exec "$PY" run.py
