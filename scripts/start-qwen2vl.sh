#!/bin/bash
# start-qwen2vl.sh — Qwen2-VL-2B llama.cpp server 优化启动脚本
#
# 使用方式:
#   docker stop qwen2vl && docker rm qwen2vl
#   bash start-qwen2vl.sh
#
# 或直接更新 docker-compose 中 qwen2vl 容器的 command。

set -euo pipefail

MODEL_DIR="${MODEL_DIR:-D:/deepseek/data/qwen2-vl-gguf}"
LLAMA_DIR="${LLAMA_DIR:-D:/deepseek/data/llamacpp/llama-b9553}"
PORT="${PORT:-8081}"
HOST_PORT="${HOST_PORT:-8082}"

# 获取宿主机 CPU 核数
if command -v nproc &>/dev/null; then
    CPU_CORES=$(nproc)
else
    CPU_CORES=16
fi
THREADS=$((CPU_CORES - 2))
if [ "$THREADS" -gt 16 ]; then THREADS=16; fi
if [ "$THREADS" -lt 4 ]; then THREADS=4; fi

echo "=== Qwen2-VL-2B llama.cpp server ==="
echo "  Model:     $MODEL_DIR/Qwen2-VL-2B-Instruct-Q4_K_M.gguf"
echo "  mmproj:    $MODEL_DIR/mmproj-Qwen2-VL-2B-Instruct-Q8_0.gguf"
echo "  Threads:   $THREADS"
echo "  Port:      $HOST_PORT -> $PORT"
echo ""

docker run -d --name qwen2vl --restart unless-stopped \
    -p "$HOST_PORT:$PORT" \
    -v "$MODEL_DIR:/models:ro" \
    -v "$LLAMA_DIR:/server:ro" \
    python:3.11-slim \
    bash -c "
        apt-get update -qq && apt-get install -y -qq libgomp1 2>/dev/null || true
        export LD_LIBRARY_PATH=/server
        exec /server/llama-server \\
            --host 0.0.0.0 --port $PORT \\
            -m /models/Qwen2-VL-2B-Instruct-Q4_K_M.gguf \\
            --mmproj /models/mmproj-Qwen2-VL-2B-Instruct-Q8_0.gguf \\
            -t $THREADS \\
            -c 4096 \\
            -b 1024 \\
            -ub 256 \\
            -np 2 \\
            --mlock \\
            --no-mmap \\
            --flash-attn \\
            --cache-type-k q8_0 \\
            --cache-type-v q8_0 \\
            --image-min-tokens 512 \\
            --image-max-tokens 2048
    "

echo ""
echo "Waiting for server..."
for i in \$(seq 1 30); do
    if curl -s http://localhost:$HOST_PORT/health | grep -q ok; then
        echo "Server ready! http://localhost:$HOST_PORT"
        exit 0
    fi
    sleep 1
done
echo "WARNING: Server did not respond within 30s"
