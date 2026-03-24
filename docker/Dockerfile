# syntax=docker/dockerfile:1
# DOCKER_BUILDKIT=1 docker compose build
# 레이어: apt → uv → torch(CPU) → requirements → 소스
# sentence-transformers 가 PyPI 기본 torch(CUDA) 를 끌어오기 전에 CPU 휠을 고정해 이미지·빌드 시간을 줄임.
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# uv / uvx 바이너리 (공식 distroless 이미지에서 복사)
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /uvx /bin/

# 1) 시스템 의존성 (자주 안 바뀜)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 2) PyTorch CPU 전용 (CUDA 휠 수 GB 방지) — sentence-transformers 보다 먼저
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

# 3) 나머지 의존성 (requirements 변경 시에만 아래 RUN 무효화)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# 원격 MCP 421 방지: TransportSecuritySettings 를 SDK에 넣을 수 있어야 함 (kwargs 또는 settings)
RUN python -c "from importlib.metadata import version; from mcp.server.fastmcp import FastMCP; from mcp.server.transport_security import TransportSecuritySettings; m=FastMCP('build-check', transport_security=TransportSecuritySettings(allowed_hosts=['build:1'])); assert m.settings.transport_security is not None; print('mcp', version('mcp'), 'transport_security OK')"

# 4) 소스는 마지막
COPY . .

# 개발: 볼륨 ..:/app + --reload (코드만 바꿀 땐 이미지 리빌드 불필요)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app"]
