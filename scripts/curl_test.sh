#!/bin/bash
# Test qwen2vl with a simple curl from inside the container
curl -v -m 30 \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2-vl",
    "messages": [{"role": "user", "content": "回复一个字：好"}],
    "max_tokens": 5,
    "temperature": 0.0
  }' \
  http://localhost:8081/v1/chat/completions
