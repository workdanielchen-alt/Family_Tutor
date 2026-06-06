#!/bin/bash
# Dev-mode startup verification
# Called by the deeptutor container entrypoint before supervisord.
# Exits non-zero if dev mode is misconfigured (e.g. "node server.js"
# instead of "next dev", or missing volume mounts).

set -euo pipefail

echo "[dev-check] Verifying development environment..."

FAIL=0
check() {
    local what="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "  [OK] $what"
    else
        echo "  [FAIL] $what"
        FAIL=1
    fi
}

# 1. System must be in NODE_ENV=development
check "NODE_ENV=development" test "${NODE_ENV:-}" = "development"

# 2. next CLI must be available
check "next CLI present" node node_modules/next/dist/bin/next --version

# 3. Source directories must be mounted (not empty)
check "web/app mounted" test -f /app/web/app/\(app\)/chat/\[\[...sessionId\]\]/page.tsx
check "web/components mounted" test -d /app/web/components/quiz
check "web/lib mounted" test -f /app/web/lib/quiz-types.ts

# 4. No stale production .next2
if test -d /app/web/.next2/standalone; then
    echo "  [WARN] Stale .next2/standalone detected — will be cleaned by next dev"
fi

# 5. supervisor config must contain "next dev", not "node server.js"
if grep -q "node server.js" /etc/supervisor/conf.d/deeptutor.conf; then
    echo "  [CRITICAL] Supervisor config contains 'node server.js' (production)!"
    echo "  This means the dev supervisor config was NOT mounted."
    echo "  Ensure docker-compose.dev.yml mounts ./docker/deeptutor-supervisord-dev.conf"
    FAIL=1
else
    echo "  [OK] Supervisor config uses dev mode (not 'node server.js')"
fi

if test "$FAIL" -ne 0; then
    echo ""
    echo "=== DEV CHECK FAILED ==="
    echo "The container is NOT properly configured for development."
    echo "Changes to source files will NOT take effect."
    echo "Please rebuild with: make dev"
    exit 1
fi

echo "[dev-check] All good — dev mode is properly configured."
