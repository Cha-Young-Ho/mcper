"""FastAPI app with MCP (Streamable HTTP) mounted and Postgres-backed tools."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.asgi.csrf_middleware import CSRFMiddleware
from app.config import settings
from app.db.database import SessionLocal, check_db_connection, init_db
from app.db.seed_defaults import (
    seed_if_empty,
    seed_repo_if_empty,
    seed_admin_user_if_empty,
)
from app.db.seed_specs import seed_sample_spec_if_empty
from app.logging_config import configure_logging
from app.mcp_app import mcp
from app.services.embeddings import configure_embedding_backend
from app.services.mcp_auto_hosts import sync_mcp_allowed_hosts
from app.services.rag_health import rag_health_payload
from app.mcp_dynamic_mount import mcp_dynamic_asgi
from app.routers import (
    admin_base,
    admin_celery,
    admin_dashboard,
    admin_docs,
    admin_rbac,
    admin_specs,
    admin_rules,
    admin_rules_app,
    admin_rules_global,
    admin_rules_repo,
    admin_skills,
    admin_workflows,
    admin_tools,
    admin_users,
)

logger = logging.getLogger("mcper.startup")

MCP_MOUNT_PATH = settings.mcp.mount_path.rstrip("/") or "/mcp"

# ── Feature Flags (환경변수 기반, 배포 환경과 무관) ─────────────────
_ADMIN_ENABLED = os.environ.get("MCPER_ADMIN_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
_MCP_ENABLED = os.environ.get("MCPER_MCP_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
_AUTH_ENABLED = os.environ.get("MCPER_AUTH_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
# MCP OAuth 는 HTTPS 필수 (RFC). HTTP 개발환경에서는 끈다. 미설정 시 _AUTH_ENABLED 따라감.
_MCP_AUTH_RAW = os.environ.get("MCPER_MCP_AUTH_ENABLED")
_MCP_AUTH_ENABLED = (
    _AUTH_ENABLED
    if _MCP_AUTH_RAW is None
    else _MCP_AUTH_RAW.lower() in ("1", "true", "yes")
)


def _validate_startup_config() -> None:
    """중요 설정 검증. 인증 활성 상태에서 보안 필수값 누락 시 startup 차단.

    - ``MCPER_AUTH_ENABLED=true`` + ``ADMIN_PASSWORD`` 미설정 → RuntimeError
    - ``MCPER_AUTH_ENABLED=true`` + ``AUTH_SECRET_KEY`` 미설정 → RuntimeError
    - ``ADMIN_PASSWORD="changeme"`` 는 마스터 단일 계정 운용 정책에 따라 허용
      (WARNING 로그만). 실제 운영에서는 변경 권장.
    """
    password = os.environ.get("ADMIN_PASSWORD", "")
    secret_key = os.environ.get("AUTH_SECRET_KEY", "") or (
        settings.auth.secret_key or ""
    )

    if _AUTH_ENABLED:
        if not password:
            raise RuntimeError(
                "MCPER_AUTH_ENABLED=true 이지만 ADMIN_PASSWORD 가 설정되지 않았습니다. "
                "반드시 안전한 값으로 설정 후 시작하세요."
            )
        if password == "changeme":
            logger.warning(
                "ADMIN_PASSWORD='changeme' — 마스터 단일 계정 운용 정책에 따라 허용. "
                "운영 배포 전 반드시 변경하세요."
            )
        if not secret_key:
            raise RuntimeError(
                "MCPER_AUTH_ENABLED=true 이지만 AUTH_SECRET_KEY(또는 auth.secret_key) 가 "
                "설정되지 않았습니다. JWT/CSRF 서명을 위해 반드시 설정하세요."
            )
    else:
        # 로컬 개발 편의: 인증 꺼진 상태에서는 INFO 로그만.
        if not password:
            logger.info("ADMIN_PASSWORD is not set (auth disabled; local dev mode).")
        elif password == "changeme":
            logger.info(
                "ADMIN_PASSWORD is default 'changeme' (auth disabled; local dev mode)."
            )


def _get_allowed_origins() -> list[str]:
    """
    CORS 허용 Origin 목록 생성 (제한적).
    1. config.security.allowed_origins (YAML)
    2. CORS_ALLOWED_ORIGINS 환경 변수 (쉼표 구분)
    3. 기본값: localhost 포트 (개발용) + Cursor IDE
    와일드카드("*")는 허용하지 않음.
    """
    origins: list[str] = []

    # config.yaml 에서
    if settings.security.allowed_origins:
        origins.extend(settings.security.allowed_origins)

    # 환경 변수에서
    env_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if env_origins:
        origins.extend([o.strip() for o in env_origins.split(",") if o.strip()])

    # 기본값: localhost + Cursor IDE
    if not origins:
        origins = [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
            "vscode-webview://",
        ]

    # 와일드카드 제거 (보안 강화)
    origins = [o for o in origins if o != "*"]

    return list(set(origins))  # 중복 제거


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    _validate_startup_config()
    configure_embedding_backend(settings.embedding)
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        seed_repo_if_empty(db)
        seed_sample_spec_if_empty(db)
        if _AUTH_ENABLED:
            seed_admin_user_if_empty(db)
        sync_mcp_allowed_hosts(db, settings)
        mcp_dynamic_asgi.init(settings)
    finally:
        db.close()
    async with mcp.session_manager.run():
        # lifespan 이 yield 지나면 startup 완료 — K8s startup probe 판정용
        _app.state.startup_done = True
        yield
        _app.state.startup_done = False


app = FastAPI(
    title="MCPER",
    description="MCP + Postgres (specs, rules) — admin at /admin",
    lifespan=lifespan,
)

# ── CORS 미들웨어 등록 (CSRF 이전) ───────────────────────────────────
allowed_origins = _get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",
        "X-Requested-With",
    ],
    expose_headers=["Content-Type"],
    max_age=86400,
)

# ── CSRF 미들웨어 등록 ────────────────────────────────────────────────
# secret_key 는 _validate_startup_config() 에서 인증 활성 시 필수 검증됨.
# 인증 비활성(로컬 개발) + admin 만 켜진 경우는 프로세스 단위 랜덤 키 자동 생성.
if _AUTH_ENABLED or _ADMIN_ENABLED:
    _csrf_secret = settings.auth.secret_key
    if not _csrf_secret:
        if _AUTH_ENABLED:
            # 검증 함수를 통과했는데 여기 오면 안 됨 — 방어적 체크.
            raise RuntimeError(
                "auth.secret_key 가 비어 있습니다. AUTH_SECRET_KEY 를 설정하세요."
            )
        import secrets as _secrets

        _csrf_secret = _secrets.token_urlsafe(32)
        logger.info(
            "auth.secret_key not configured; generated ephemeral CSRF key "
            "(auth disabled, local dev mode)."
        )
    app.add_middleware(
        CSRFMiddleware,
        secret_key=_csrf_secret,
        cookie_secure=settings.security.secure_cookie,
    )

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── 조건부 라우터 등록 ──────────────────────────────────────────────
if _ADMIN_ENABLED:
    app.include_router(admin_base.router)
    app.include_router(admin_dashboard.router)
    app.include_router(admin_specs.router)
    app.include_router(admin_rules.router)
    app.include_router(admin_rules_global.router)
    app.include_router(admin_rules_app.router)
    app.include_router(admin_rules_repo.router)
    app.include_router(admin_skills.router)
    app.include_router(admin_tools.router)
    app.include_router(admin_celery.router)
    app.include_router(admin_rbac.router)
    app.include_router(admin_users.router)
    app.include_router(admin_workflows.router)
    app.include_router(admin_docs.router)
    logger.info("Admin UI enabled at /admin")

if _AUTH_ENABLED:
    from app.auth.router import router as auth_router
    from app.auth.oauth import router as oauth_router

    app.include_router(auth_router)
    # Google/GitHub OAuth: client_id 설정 시에만 등록
    if settings.auth.google_client_id or settings.auth.github_client_id:
        app.include_router(oauth_router)
    logger.info("Authentication enabled")

if _MCP_ENABLED:
    app.mount(MCP_MOUNT_PATH, mcp_dynamic_asgi)
    logger.info("MCP endpoint enabled at %s", MCP_MOUNT_PATH)

    # ── OAuth disabled: RFC 6749 호환 stub 응답 ─────────────────────────
    # MCP 클라이언트가 저장된 이전 OAuth state 때문에 /register, /token 등을 호출할 때
    # FastAPI 기본 404 ({"detail": "Not Found"}) 는 OAuth 에러 스키마가 아니라 클라이언트 SDK 파싱 실패.
    # RFC 6749 §5.2 형식으로 응답해 클라이언트가 깔끔하게 OAuth 비활성을 인지하도록 한다.
    if not _MCP_AUTH_ENABLED:
        from fastapi.responses import JSONResponse as _JSON

        _OAUTH_DISABLED_BODY = {
            "error": "unsupported_response_type",
            "error_description": "OAuth is not configured on this server",
        }

        def _oauth_disabled_response() -> Response:
            return _JSON(status_code=404, content=_OAUTH_DISABLED_BODY)

        @app.post("/register")
        @app.get("/register")
        def _oauth_register_disabled() -> Response:
            return _oauth_disabled_response()

        @app.post("/token")
        @app.get("/token")
        def _oauth_token_disabled() -> Response:
            return _oauth_disabled_response()

        @app.post("/revoke")
        @app.get("/revoke")
        def _oauth_revoke_disabled() -> Response:
            return _oauth_disabled_response()

        @app.post("/authorize")
        @app.get("/authorize")
        def _oauth_authorize_disabled() -> Response:
            return _oauth_disabled_response()

    # ── MCP OAuth well-known + endpoint proxies at root ──────────────
    # RFC 9728/8414 require well-known URLs at the root, not inside the mount.
    # Also, some MCP clients resolve OAuth endpoints relative to the root.
    if _MCP_AUTH_ENABLED:
        from app.auth.mcp_oauth_provider import MCP_SCOPES

        def _mcp_base_url() -> tuple[str, str]:
            _port = os.environ.get("PORT") or os.environ.get("UVICORN_PORT") or "8001"
            _host = os.environ.get("MCPER_PUBLIC_HOST") or f"localhost:{_port}"
            _sch = os.environ.get("MCPER_PUBLIC_SCHEME") or (
                "https" if ("443" in _host or _MCP_AUTH_ENABLED) else "http"
            )
            _mount = MCP_MOUNT_PATH.rstrip("/") or "/mcp"
            return f"{_sch}://{_host}", _mount

        @app.get("/.well-known/oauth-protected-resource{path:path}")
        def protected_resource_metadata(path: str = "") -> Response:
            """RFC 9728 Protected Resource Metadata."""
            _base, _mount = _mcp_base_url()
            return {
                "resource": f"{_base}{_mount}/",
                "authorization_servers": [f"{_base}{_mount}"],
                "scopes_supported": MCP_SCOPES,
                "bearer_methods_supported": ["header"],
            }

        @app.get("/.well-known/oauth-authorization-server{path:path}")
        def authorization_server_metadata(path: str = "") -> Response:
            """RFC 8414 Authorization Server Metadata (proxy to MCP mount)."""
            _base, _mount = _mcp_base_url()
            from app.auth.mcp_oauth_provider import MCP_SCOPES

            return {
                "issuer": f"{_base}{_mount}",
                "authorization_endpoint": f"{_base}{_mount}/authorize",
                "token_endpoint": f"{_base}{_mount}/token",
                "registration_endpoint": f"{_base}{_mount}/register",
                "scopes_supported": MCP_SCOPES,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_post",
                    "client_secret_basic",
                ],
                "revocation_endpoint": f"{_base}{_mount}/revoke",
                "revocation_endpoint_auth_methods_supported": [
                    "client_secret_post",
                    "client_secret_basic",
                ],
                "code_challenge_methods_supported": ["S256"],
            }


# ── Health Endpoints (항상 활성) ────────────────────────────────────
# K8s/LB probe 표준 3단계 분리 (L09):
#   /health/live    — 프로세스 응답성만 (의존 없음) — liveness
#   /health/ready   — DB + Redis + 임베딩 준비 확인 — readiness
#   /health/startup — lifespan 완료 여부 — startup
# /health 는 기존 호환 alias (deprecated), /health/rag 는 관측용 그대로 유지.

from fastapi import Request as _HealthReq  # noqa: E402  — 헬스 블록 분리 위치
from app.services.health import (  # noqa: E402
    liveness_payload as _liveness_payload,
    readiness_payload as _readiness_payload,
    startup_payload as _startup_payload,
)


def _startup_done(request: _HealthReq) -> bool:
    return bool(getattr(request.app.state, "startup_done", False))


@app.get("/health/live")
async def health_live() -> Response:
    """Liveness probe — 프로세스 이벤트 루프 응답성만 확인."""
    return await _liveness_payload()


@app.get("/health/ready")
async def health_ready(request: _HealthReq) -> Response:
    """Readiness probe — DB + Redis + 임베딩 backend 준비 확인."""
    payload, status = await _readiness_payload(startup_done=_startup_done(request))
    if status != 200:
        return JSONResponse(status_code=status, content=payload)
    return payload


@app.get("/health/startup")
async def health_startup(request: _HealthReq) -> Response:
    """Startup probe — lifespan 완료 여부. 완료 후 readiness 동일."""
    payload, status = await _startup_payload(_startup_done(request))
    if status != 200:
        return JSONResponse(status_code=status, content=payload)
    return payload


@app.get("/health")
async def health(request: _HealthReq) -> Response:
    """Deprecated: 기존 클라이언트 호환용. 신규는 /health/ready 사용.

    응답은 /health/ready 로직 복제 — 503 조건 동일.
    """
    payload, status = await _readiness_payload(startup_done=_startup_done(request))
    if status != 200:
        return JSONResponse(status_code=status, content=payload)
    return payload


@app.get("/health/rag")
def health_rag() -> Response:
    """RAG/Celery 부하 관측: DB + (가능하면) Redis 브로커·기본 큐 깊이."""
    if not check_db_connection():
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "down"},
        )
    return {"status": "ok", "database": "up", **rag_health_payload()}
