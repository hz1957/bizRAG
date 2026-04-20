FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY file_service/requirements.txt /app/file_service/requirements.txt
RUN pip install --no-cache-dir -r /app/file_service/requirements.txt

COPY file_service /app/file_service

RUN mkdir -p /app/runtime/file_service/storage /app/runtime/file_service/state

EXPOSE 8002
CMD ["python", "-m", "file_service.run"]
