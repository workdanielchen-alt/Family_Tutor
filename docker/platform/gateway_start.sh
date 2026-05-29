#!/bin/bash
# Gateway startup script for WeChat iLink dual-bot gateway.
# Starts parent gateway (main) and child gateway (sub) in the same container.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/hermes"

# Activate virtual environment
source "${INSTALL_DIR}/.venv/bin/activate"

# Child gateway with auto-restart supervision
# The while-true loop ensures persistence: if the process crashes or the iLink
# session dies, the child restarts within 3 seconds without requiring a full
# container restart (which would risk >5min downtime and session loss).
_child_restart_loop() {
  while true; do
    WEIXIN_TOKEN="$CHILD_WEIXIN_TOKEN" \
    WEIXIN_ACCOUNT_ID="$CHILD_WEIXIN_ACCOUNT_ID" \
    API_SERVER_ENABLED=false \
    API_SERVER_KEY="" \
    HERMES_HOME=/opt/data/child \
    hermes gateway run --accept-hooks
    EXIT_CODE=$?
    echo "[child] gateway exited (code $EXIT_CODE), restarting in 3s..."
    sleep 3
  done
}
_child_restart_loop &
CHILD_PID=$!
echo "Child gateway supervisor started (PID=$CHILD_PID)"

# Start parent gateway in foreground
exec hermes gateway run --accept-hooks
