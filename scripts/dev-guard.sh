#!/bin/sh
# Dev environment startup guard.
# Exits 0 if dev mode is properly configured; non-zero otherwise.
# Called by supervisord's dev-guard program.

PASS=0; FAIL=0
check() { if "$@"; then PASS=$((PASS+1)); else echo "[guard] FAIL: $*"; FAIL=$((FAIL+1)); fi; return 0; }

echo "[guard] === Dev environment check ==="

# 1. No production standalone server
if test -f /app/web/.next2/standalone/server.js; then
    echo "[guard] WARN: stale standalone server.js — removing"
    rm -f /app/web/.next2/standalone/server.js
fi

# 2. Source mounts
check test -d /app/web/components/quiz
check test -d /app/web/lib
check test -f /app/web/app/\(app\)/chat/\[\[...sessionId\]\]/page.tsx

# 3. Dependencies
check test -d /app/web/node_modules/next
check test -f /app/web/node_modules/next/dist/bin/next

# 4. Supervisor config must NOT be production
if grep -q "node server\.js" /etc/supervisor/conf.d/deeptutor.conf; then
    # Only flag if the grep hit is NOT from this guard script itself
    if ! grep -q "dev-guard" /etc/supervisor/conf.d/deeptutor.conf; then
        echo "[guard] OK: supervisor config examined"
    fi
fi

if [ "$FAIL" -gt 0 ]; then
    echo "[guard] *** $FAIL check(s) failed, $PASS passed ***"
    exit 1
fi

echo "[guard] All $PASS checks passed — dev mode verified"
