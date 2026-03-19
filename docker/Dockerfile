FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# --reload-dir 로 감시 범위 명시 (볼륨 마운트된 /app 만)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app"]
