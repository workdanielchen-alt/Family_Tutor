#!/bin/bash
# Hot-patch: remove Figures tab from production Next.js build
# Source files are already fixed; this covers stale container builds
CHUNK=$(find /app/web/.next2/static/chunks -name '*.js' -exec grep -l 'figures' {} \; 2>/dev/null | head -1)
if [ -n "$CHUNK" ]; then
    sed -i 's/{key:"figures",label:"Figures",Icon:I.Image},//g' "$CHUNK"
    sed -i 's/new Set(\["files","figures"\])/new Set(["files"])/g' "$CHUNK"
    sed -i 's/"figures"===f&&(0,r.jsx)(ei,{kb:e},e.name),//g' "$CHUNK"
    echo "[patch] Removed Figures tab from stale build chunk: $CHUNK"
fi
