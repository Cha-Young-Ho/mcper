"""YAML + 환경변수 부트스트랩.

우선순위: **YAML(및 ``${VAR}`` / ``${VAR:-기본값}`` 치환) < 표준 환경변수** (덮어쓰기).
``pydantic-settings`` 로 ``DATABASE_URL`` 등 표준 env 키를 검증해 읽는다.
MCP ``Host`` 허용 목록은 YAML이 아니라 어드민 DB.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, BaseModel, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ${VAR} 또는 ${VAR:-default} (default 는 '}' 를 포함하지 않음)
_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ServerSettings(BaseModel):
    """Uvicorn 이 컨테이너 안에서 듣는 주소."""

    host: str = "0.0.0.0"
    port: int = 8000


class McpSettings(BaseModel):
    mount_path: str = "/mcp"


class SecuritySettings(BaseModel):
    """MCP ``allowed_origins`` YAML 기본값. Host 는 DB(어드민)에서 관리."""

    allowed_origins: list[str] = Field(default_factory=list)


class DatabaseSettings(BaseModel):
    """비어 있으면 ``DATABASE_URL`` 환경변수 사용."""

    url: str | None = None


class CelerySettings(BaseModel):
    """선택. 워커는 여전히 주로 ``CELERY_*`` env 를 쓰지만, 설정 단일화용."""

    broker_url: str | None = None
    result_backend: str | None = None


class AppSettings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    #: ``spec_chunks`` / ``code_nodes`` 의 pgvector 차원(모델 출력과 동일해야 함).
    embedding_dim: int = 384
    #: 로컬 임베딩 로더(``app.services.embeddings``)에서 쓰는 sentence-transformers 모델 id.
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @computed_field
    def celery_enabled(self) -> bool:
        return bool((self.celery.broker_url or "").strip())


class EnvBootstrapSettings(BaseSettings):
    """표준 배포 env — YAML 보다 우선 (pydantic-settings)."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL"),
    )
    celery_broker_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CELERY_BROKER_URL"),
    )
    celery_result_backend: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CELERY_RESULT_BACKEND"),
    )
    port: int | None = Field(default=None, validation_alias=AliasChoices("PORT"))
    uvicorn_host: str | None = Field(
        default=None, validation_alias=AliasChoices("UVICORN_HOST")
    )
    uvicorn_port: int | None = Field(
        default=None, validation_alias=AliasChoices("UVICORN_PORT")
    )
    mcp_allowed_origins: str | None = Field(
        default=None, validation_alias=AliasChoices("MCP_ALLOWED_ORIGINS")
    )
    embedding_dim: int | None = Field(
        default=None, validation_alias=AliasChoices("EMBEDDING_DIM")
    )
    local_embedding_model: str | None = Field(
        default=None, validation_alias=AliasChoices("LOCAL_EMBEDDING_MODEL")
    )


def _expand_env_in_str(s: str) -> str:
    if "${" not in s:
        return s

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        val = os.environ.get(key)
        if val is not None and val != "":
            return val
        if default is not None:
            return default
        return match.group(0)

    return _ENV_PLACEHOLDER.sub(repl, s)


def expand_env_placeholders(obj: Any) -> Any:
    """YAML 로드 직후, 문자열 안의 ``${VAR}`` / ``${VAR:-def}`` 를 os.environ 으로 치환."""
    if isinstance(obj, str):
        return _expand_env_in_str(obj)
    if isinstance(obj, dict):
        return {k: expand_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_placeholders(v) for v in obj]
    return obj


def _config_path() -> Path:
    raw = (os.environ.get("MCPER_CONFIG") or os.environ.get("MCPER_CONFIG_PATH") or "").strip()
    if raw:
        return Path(raw)
    root = Path(__file__).resolve().parent.parent
    return root / "config.yaml"


def load_settings() -> AppSettings:
    path = _config_path()
    data: dict[str, Any] = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                data = expand_env_placeholders(loaded)

    cfg = AppSettings.model_validate(data)

    env = EnvBootstrapSettings()

    if env.database_url:
        cfg.database.url = env.database_url
    if env.celery_broker_url:
        cfg.celery.broker_url = env.celery_broker_url
    if env.celery_result_backend:
        cfg.celery.result_backend = env.celery_result_backend

    if env.port is not None:
        cfg.server.port = env.port
    if env.uvicorn_host:
        cfg.server.host = env.uvicorn_host.strip()
    if env.uvicorn_port is not None:
        cfg.server.port = env.uvicorn_port

    if env.mcp_allowed_origins:
        merged = list(cfg.security.allowed_origins)
        merged.extend(
            x.strip() for x in env.mcp_allowed_origins.split(",") if x.strip()
        )
        cfg.security.allowed_origins = list(dict.fromkeys(merged))

    if env.embedding_dim is not None:
        cfg.embedding_dim = env.embedding_dim
    if env.local_embedding_model:
        cfg.local_embedding_model = env.local_embedding_model

    return cfg


# 프로세스당 한 번 로드 (필요 시 테스트에서 재할당)
settings: AppSettings = load_settings()
