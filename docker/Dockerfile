FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    HF_HUB_CACHE=/app/.cache/huggingface/hub \
    MODELSCOPE_CACHE=/app/.cache/huggingface/hub/modelscope

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    catdoc \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.11.0,<2.12.0"

RUN pip install -e ".[mq,eval]"

RUN pip install "mineru[core]>=3.0.0,<4"

# MinerU pulls torchvision from the default index; force the matching CPU wheel
# back in place so sentence-transformers/transformers can import reliably.
RUN pip install --index-url https://download.pytorch.org/whl/cpu --no-deps --force-reinstall \
    "torch==2.11.0+cpu" \
    "torchvision==0.26.0+cpu"

RUN mkdir -p /app/runtime /app/logs /app/output /app/raw_knowledge /app/.cache/huggingface/hub/modelscope \
    && chmod +x /app/docker/start_bizrag.sh

EXPOSE 64501

CMD ["/app/docker/start_bizrag.sh"]
