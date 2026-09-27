#!/usr/bin/env bash
# 本地专属监控：只跑 monitor_scope=local 的目标，并自动提交结果（不 push）。
#
# 用途：GitHub runner 连不上的站点（目前是 trae —— Cloudflare 拒绝数据中心 IP，
# describe_shell() 显示"实际拿到：空文档"），改由本地跑，以本地结果为准。
# 见 site/docs/update-monitoring.md 的"本地专属监控"一节。
#
# 用法：
#   ./scripts/local_monitor.sh              # 跑全部本地专属目标
#   ./scripts/local_monitor.sh --only trae:main --timeout 60   # 只跑一个目标
#
# 只提交监控产物（状态/队列/快照），不会捎带上工作区里其他未提交改动；
# push 留给你手动确认——push 到 main 会触发 CI 与 Pages 真实发布。
set -euo pipefail

cd "$(dirname "$0")/.."

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[错误] 未找到 .venv，请先执行 ./start.sh 创建虚拟环境并安装依赖" >&2
  exit 1
fi

echo "=== 本地专属监控（monitor_scope=local）==="
"$PY" scripts/check_updates.py --scope local "$@"

echo
echo "=== 提交监控产物（不 push）==="
git add site/generated/update_status.json \
        site/generated/monitor_health.json \
        site/generated/pending_verification.json \
        site/generated/snapshots

if git diff --cached --quiet; then
  echo "无监控产物变化，跳过提交"
  exit 0
fi

git -c user.name="$(git config user.name)" \
    -c user.email="$(git config user.email)" \
    commit -q -m "monitor(local): 本地专属监控 $(date +%F)"

echo "已提交。查看与推送："
echo "  git show --stat HEAD"
echo "  git push origin main    # 会触发 CI 与 Pages 发布"
