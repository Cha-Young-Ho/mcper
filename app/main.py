"""FastAPI app with MCP (Streamable HTTP) mounted and Postgres-backed tools."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import SessionLocal, check_db_connection, init_db
from app.db.seed_defaults import seed_if_empty, seed_repo_if_empty
from app.db.seed_specs import seed_sample_spec_if_empty
from app.mcp_app import mcp
from app.routers import admin as admin_routes

MCP_MOUNT_PATH = "/mcp"

# session_manager는 streamable_http_app() 호출 후에만 사용 가능
mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """DB 마이그레이션 + MCP Streamable HTTP 세션 매니저."""
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        seed_repo_if_empty(db)
        seed_sample_spec_if_empty(db)
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


@app.get("/health")
def health():
    """Liveness/readiness: returns 503 if DB is unreachable."""
    if not check_db_connection():
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "down"},
        )
    return {"status": "ok", "database": "up"}


app.include_router(admin_routes.router)
app.mount(MCP_MOUNT_PATH, mcp_http_app)
