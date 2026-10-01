#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p .local/web
if ! curl --silent --fail http://127.0.0.1:8765/health >/dev/null; then
  nohup .venv/bin/python -m webui.server >.local/web/server.log 2>&1 </dev/null &
fi
if [ -n "${CODESPACE_NAME:-}" ]; then
  # Codespaces forwards privately by default; also request it explicitly.
  gh codespace ports visibility 8765:private -c "$CODESPACE_NAME" >/dev/null 2>&1 || true
fi
printf '\n火花小助手已启动。打开下方 Ports → 8765 → 在浏览器中打开。\n端口必须保持 Private（私有），不要改成 Public。\n'
