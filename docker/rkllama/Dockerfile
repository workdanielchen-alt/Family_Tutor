FROM python:3.11-slim
WORKDIR /app

# Install FastAPI + dependencies for rkllama server
RUN pip install --no-cache-dir fastapi uvicorn pydantic

# Copy server files (model_registry.py is bundled inside the image if present)
COPY rkllama_server.py /app/
COPY model_registry.py /app/ 2>/dev/null || true

# Runtime config
ENV RKLLM_PORT=8080
ENV RKLLM_STUB_MODE=true

EXPOSE 8080

CMD ["python", "rkllama_server.py"]
