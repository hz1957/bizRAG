FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    catdoc \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.11.0,<2.12.0"

RUN pip install -e ".[mq]"

RUN pip install "mineru[core]>=3.0.0,<4"

RUN mkdir -p /app/runtime /app/logs /app/output /app/raw_knowledge /app/.cache/huggingface \
    && chmod +x /app/docker/start_bizrag.sh

EXPOSE 64501

CMD ["/app/docker/start_bizrag.sh"]
