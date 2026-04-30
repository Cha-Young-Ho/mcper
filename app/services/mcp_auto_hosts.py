"""기동 시 MCP 허용 Host 를 DB에 자동 등록 (어드민 수동 입력 제거).

우선순위:
1. ``MCP_ALLOWED_HOSTS`` — 쉼표로 여러 개 (ALB DNS, 고정 도메인 등 공유 DB 인스턴스에 권장)
2. ``MCP_PUBLIC_HOST`` — 단일 ``host:port``
3. ``MCP_AUTO_EC2_PUBLIC_IP`` (기본 1) — EC2 IMDS 로 public IPv4 + ``MCP_EXTERNAL_PORT`` (기본 8001, 호스트 매핑 포트)
4. 항상 ``127.0.0.1:{listen}``, ``localhost:{listen}`` (컨테이너 내부 listen 포트 기준)

오토스케일: Host 헤더는 보통 **ALB 단일 호스트명**이므로 ``MCP_ALLOWED_HOSTS`` 에 ALB DNS:443(또는 포트)을 넣으면
모든 태스크가 같은 행을 쓰면 된다. 인스턴스별 퍼블릭 IP는 IMDS 로 **추가(INSERT OR IGNORE)** 되며,
옛 IP 행은 자동 삭제하지 않는다(필요 시 ``MCP_ALLOWED_HOSTS`` 만 쓰고 ``MCP_AUTO_EC2_PUBLIC_IP=0``).
"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.db.mcp_security import McpAllowedHost

logger = logging.getLogger(__name__)

_METADATA_TOKEN_URL = "http://169.254.169.254/latest/api/token"
_METADATA_PUBLIC_IPV4 = "http://169.254.169.254/latest/meta-data/public-ipv4"


def _split_hosts(raw: str) -> list[str]:
    return [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]


def _ec2_public_ipv4() -> str | None:
    """IMDSv2 우선, 실패 시 IMDSv1."""
    try:
        req = urllib.request.Request(
            _METADATA_TOKEN_URL,
            data=b"",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            token = resp.read().decode("ascii").strip()
        req2 = urllib.request.Request(
            _METADATA_PUBLIC_IPV4,
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(req2, timeout=1.5) as resp:
            ip = resp.read().decode("ascii").strip()
        return ip or None
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        pass
    try:
        with urllib.request.urlopen(_METADATA_PUBLIC_IPV4, timeout=1.0) as resp:
            ip = resp.read().decode("ascii").strip()
        return ip or None
    except (OSError, urllib.error.URLError):
        return None


def collect_host_entries(app_settings: AppSettings) -> list[str]:
    listen_port = int(app_settings.server.port)
    out: list[str] = []
    seen: set[str] = set()

    def add(h: str) -> None:
        h = h.strip()
        if h and h not in seen:
            seen.add(h)
            out.append(h)

    raw = (os.environ.get("MCP_ALLOWED_HOSTS") or "").strip()
    if raw:
        for h in _split_hosts(raw):
            add(h)

    single = (os.environ.get("MCP_PUBLIC_HOST") or "").strip()
    if single:
        add(single)

    if os.environ.get("MCP_AUTO_EC2_PUBLIC_IP", "1").strip() not in (
        "0",
        "false",
        "no",
    ):
        ip = _ec2_public_ipv4()
        if ip:
            ext_port = (os.environ.get("MCP_EXTERNAL_PORT") or "8001").strip()
            add(f"{ip}:{ext_port}")

    for h in (f"127.0.0.1:{listen_port}", f"localhost:{listen_port}"):
        add(h)

    return out


def sync_mcp_allowed_hosts(session: Session, app_settings: AppSettings) -> list[str]:
    """수집한 Host 목록을 DB에 없으면 INSERT. 기존 행은 삭제하지 않음."""
    entries = collect_host_entries(app_settings)
    if not entries:
        logger.warning("MCP 허용 Host 가 비어 있음 — MCP 연결 시 Host 검사 실패 가능")
        return []

    # select(컬럼만) 이면 스칼라가 str 등으로 온다 (ORM 행이 아님).
    existing = {
        str(r).strip() for r in session.scalars(select(McpAllowedHost.host_entry)).all()
    }
    added: list[str] = []
    for h in entries:
        if h in existing:
            continue
        session.add(McpAllowedHost(host_entry=h, note="auto"))
        existing.add(h)
        added.append(h)
    if added:
        session.commit()
        logger.info("MCP 허용 Host 자동 등록: %s", added)
    return entries
