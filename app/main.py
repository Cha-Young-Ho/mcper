"""FastAPI app with MCP (Streamable HTTP) mounted and Postgres-backed tools."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
from app.routers import admin as admin_routes

logger = logging.getLogger("mcper.startup")

MCP_MOUNT_PATH = settings.mcp.mount_path.rstrip("/") or "/mcp"

# ── Feature Flags (환경변수 기반, 배포 환경과 무관) ─────────────────
_ADMIN_ENABLED = os.environ.get("MCPER_ADMIN_ENABLED", "true").lower() not in ("0", "false", "no")
_MCP_ENABLED   = os.environ.get("MCPER_MCP_ENABLED",   "true").lower() not in ("0", "false", "no")
_AUTH_ENABLED  = os.environ.get("MCPER_AUTH_ENABLED",  "false").lower() in ("1", "true", "yes")


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
    if _AUTH_ENABLED and not os.environ.get("AUTH_SECRET_KEY", ""):
        logger.error(
            "MCPER_AUTH_ENABLED=true but AUTH_SECRET_KEY is not set. "
            "JWT signing will fail. Please set AUTH_SECRET_KEY."
        )


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

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── 조건부 라우터 등록 ──────────────────────────────────────────────
if _ADMIN_ENABLED:
    app.include_router(admin_routes.router)
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
