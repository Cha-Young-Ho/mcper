# syntax=docker/dockerfile:1
# DOCKER_BUILDKIT=1 docker compose build
# Layers: apt → uv → torch(CPU) → requirements → source
FROM python:3.13.2-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# uv / uvx binaries
COPY --from=ghcr.io/astral-sh/uv:0.6.12 /uv /uvx /bin/

# 1) System dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# 2) PyTorch CPU only (CUDA 수GB 방지) — sentence-transformers 전에 설치
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

# 3) Remaining dependencies (requirements.txt 변경 시에만 재빌드)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# 빌드 검증: mcp transport_security
RUN python -c "\
from mcp.server.fastmcp import FastMCP; \
from mcp.server.transport_security import TransportSecuritySettings; \
m=FastMCP('check', transport_security=TransportSecuritySettings(allowed_hosts=['build:1'])); \
assert m.settings.transport_security is not None; \
print('mcp transport_security OK')"

# 4) 소스 코드 (코드만 변경 시 가장 빠름)
COPY . .

# 프로덕션 기본 CMD (개발 환경은 docker-compose.override.yml에서 --reload 추가)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
