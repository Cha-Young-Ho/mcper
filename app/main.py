"""FastAPI app with MCP (Streamable HTTP) mounted and Postgres-backed tools."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.asgi.csrf_middleware import CSRFMiddleware
from app.config import settings
from app.db.database import SessionLocal, check_db_connection, init_db
from app.db.seed_defaults import seed_if_empty, seed_repo_if_empty, seed_admin_user_if_empty
from app.db.seed_specs import seed_sample_spec_if_empty
from app.logging_config import configure_logging
from app.mcp_app import mcp
from app.services.embeddings import configure_embedding_backend
from app.services.mcp_auto_hosts import sync_mcp_allowed_hosts
from app.services.rag_health import rag_health_payload
from app.mcp_dynamic_mount import mcp_dynamic_asgi
from app.routers import admin_base, admin_celery, admin_dashboard, admin_rbac, admin_specs, admin_rules, admin_skills, admin_workflows, admin_tools, admin_users

logger = logging.getLogger("mcper.startup")

MCP_MOUNT_PATH = settings.mcp.mount_path.rstrip("/") or "/mcp"

# ── Feature Flags (환경변수 기반, 배포 환경과 무관) ─────────────────
_ADMIN_ENABLED = os.environ.get("MCPER_ADMIN_ENABLED", "true").lower() not in ("0", "false", "no")
_MCP_ENABLED   = os.environ.get("MCPER_MCP_ENABLED",   "true").lower() not in ("0", "false", "no")
_AUTH_ENABLED  = os.environ.get("MCPER_AUTH_ENABLED",  "false").lower() in ("1", "true", "yes")
# MCP OAuth 는 HTTPS 필수 (RFC). HTTP 개발환경에서는 끈다. 미설정 시 _AUTH_ENABLED 따라감.
_MCP_AUTH_RAW = os.environ.get("MCPER_MCP_AUTH_ENABLED")
_MCP_AUTH_ENABLED = (
    _AUTH_ENABLED if _MCP_AUTH_RAW is None
    else _MCP_AUTH_RAW.lower() in ("1", "true", "yes")
)


def _validate_startup_config() -> None:
    """중요 설정 누락 시 경고/에러 출력."""
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        logger.warning(
            "ADMIN_PASSWORD is not set. "
            "Admin UI access requires ADMIN_PASSWORD to be configured."
        )
    elif password == "changeme":
        logger.warning(
            "ADMIN_PASSWORD is set to default 'changeme'. "
            "Change this before exposing to any network."
        )
        if _AUTH_ENABLED:
            logger.error(
                "CRITICAL: MCPER_AUTH_ENABLED=true with default ADMIN_PASSWORD. "
                "Set new ADMIN_PASSWORD in environment or change via /auth/change-password-forced"
            )
    if _AUTH_ENABLED and not os.environ.get("AUTH_SECRET_KEY", ""):
        logger.error(
            "MCPER_AUTH_ENABLED=true but AUTH_SECRET_KEY is not set. "
            "JWT signing will fail. Please set AUTH_SECRET_KEY."
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
async def lifespan(_app: FastAPI):
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
        yield


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
if _AUTH_ENABLED or _ADMIN_ENABLED:
    app.add_middleware(
        CSRFMiddleware,
        secret_key=settings.auth.secret_key or "default-csrf-key",
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
    app.include_router(admin_skills.router)
    app.include_router(admin_tools.router)
    app.include_router(admin_celery.router)
    app.include_router(admin_rbac.router)
    app.include_router(admin_users.router)
    app.include_router(admin_workflows.router)
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

    # ── MCP OAuth well-known + endpoint proxies at root ──────────────
    # RFC 9728/8414 require well-known URLs at the root, not inside the mount.
    # Also, some MCP clients resolve OAuth endpoints relative to the root.
    if _MCP_AUTH_ENABLED:
        from app.auth.mcp_oauth_provider import MCP_SCOPES
        from fastapi import Request as _Req
        from fastapi.responses import Response as _Resp
        import httpx

        def _mcp_base_url() -> tuple[str, str]:
            _port = os.environ.get("PORT") or os.environ.get("UVICORN_PORT") or "8001"
            _host = os.environ.get("MCPER_PUBLIC_HOST") or f"localhost:{_port}"
            _sch = "https" if "443" in _host else "http"
            _mount = MCP_MOUNT_PATH.rstrip("/") or "/mcp"
            return f"{_sch}://{_host}", _mount

        @app.get("/.well-known/oauth-protected-resource{path:path}")
        def protected_resource_metadata(path: str = ""):
            """RFC 9728 Protected Resource Metadata."""
            _base, _mount = _mcp_base_url()
            return {
                "resource": f"{_base}{_mount}/",
                "authorization_servers": [f"{_base}{_mount}"],
                "scopes_supported": MCP_SCOPES,
                "bearer_methods_supported": ["header"],
            }

        @app.get("/.well-known/oauth-authorization-server{path:path}")
        def authorization_server_metadata(path: str = ""):
            """RFC 8414 Authorization Server Metadata (proxy to MCP mount)."""
            _base, _mount = _mcp_base_url()
            from app.auth.mcp_oauth_provider import MCP_SCOPES
            from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
            return {
                "issuer": f"{_base}{_mount}",
                "authorization_endpoint": f"{_base}{_mount}/authorize",
                "token_endpoint": f"{_base}{_mount}/token",
                "registration_endpoint": f"{_base}{_mount}/register",
                "scopes_supported": MCP_SCOPES,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
                "revocation_endpoint": f"{_base}{_mount}/revoke",
                "revocation_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
                "code_challenge_methods_supported": ["S256"],
            }


# ── Health Endpoints (항상 활성) ────────────────────────────────────

@app.get("/health")
def health():
    """Liveness/readiness: returns 503 if DB is unreachable."""
    if not check_db_connection():
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "down"},
        )
    return {"status": "ok", "database": "up"}


@app.get("/health/rag")
def health_rag():
    """RAG/Celery 부하 관측: DB + (가능하면) Redis 브로커·기본 큐 깊이."""
    if not check_db_connection():
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "down"},
        )
    return {"status": "ok", "database": "up", **rag_health_payload()}
