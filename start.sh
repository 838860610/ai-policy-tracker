#!/usr/bin/env bash
# 一键启动本地服务：自动创建虚拟环境、安装依赖、打开浏览器。
# 用法：./start.sh [端口]    （默认 8080）
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8080}"

if [ ! -x .venv/bin/python ]; then
  echo "首次运行：创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi

echo "检查/安装依赖 ..."
.venv/bin/python -m pip install --quiet -r requirements.txt

# 服务就绪后自动打开浏览器（macOS: open / Linux: xdg-open），失败不影响服务
(
  sleep 1
  if command -v open >/dev/null 2>&1; then open "http://localhost:$PORT"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$PORT"
  fi
) >/dev/null 2>&1 &

echo "本地服务已启动: http://localhost:$PORT  （Ctrl-C 停止）"
exec .venv/bin/python -m http.server "$PORT"
