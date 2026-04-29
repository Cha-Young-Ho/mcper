"""YAML + 환경변수 부트스트랩.

우선순위: **YAML(및 ``${VAR}`` / ``${VAR:-기본값}`` 치환) < 표준 환경변수** (덮어쓰기).
``pydantic-settings`` 로 ``DATABASE_URL`` 등 표준 env 키를 검증해 읽는다.

**YAML 파일 선택**

- ``MCPER_CONFIG`` / ``MCPER_CONFIG_PATH``: 단일 YAML 경로 (지정 시 **그 파일만** 로드, 환경 병합 없음).
- 미지정 시: 리포 루트 ``config.yaml`` 을 읽고, ``MCPER_ENV`` 또는 ``APP_ENV`` 가 있으면
  ``config.<env>.yaml`` 을 **깊게 병합** (중첩 dict 는 합치고, 환경 파일 값이 우선).

MCP ``Host`` 허용 목록은 **환경변수 자동 등록** + DB(기존 행 유지); 수동 어드민 등록은 제거됨.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProvider = Literal["local", "openai", "localhost", "bedrock"]


class AuthSettings(BaseModel):
    """JWT 기반 세션 인증 설정. MCPER_AUTH_ENABLED=true 시 활성화."""

    enabled: bool = False
    # auth.enabled=true 일 때 반드시 값 설정. None 이면 main.py 검증에서 차단.
    secret_key: str | None = None
    token_expire_minutes: int = 1440
    # OAuth (optional — 클라이언트 ID 설정 시 자동 활성화)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ServerSettings(BaseModel):
    """Uvicorn 이 컨테이너 안에서 듣는 주소."""

    host: str = "0.0.0.0"
    port: int = 8000


class McpSettings(BaseModel):
    mount_path: str = "/mcp"


class SecuritySettings(BaseModel):
    """MCP ``allowed_origins`` YAML 기본값. Host 는 ``MCP_ALLOWED_HOSTS`` 등 env + 기동 시 DB 동기화."""

    allowed_origins: list[str] = Field(default_factory=list)
    secure_cookie: bool = True  # HTTPS only 쿠키 (로컬 개발: false)


class DatabaseSettings(BaseModel):
    """비어 있으면 ``DATABASE_URL`` 환경변수 사용."""

    url: str | None = None


class CelerySettings(BaseModel):
    """선택. 워커는 여전히 주로 ``CELERY_*`` env 를 쓰지만, 설정 단일화용."""

    broker_url: str | None = None
    result_backend: str | None = None


class EmbeddingSettings(BaseModel):
    """RAG 임베딩 백엔드. ``dim`` 은 pgvector 컬럼·모델 출력과 반드시 일치."""

    provider: EmbeddingProvider = "local"
    dim: int = 384
    #: ``provider == local`` 일 때 sentence-transformers 모델 id
    local_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    #: OpenAI / OpenAI 호환 ``/v1/embeddings``
    openai_api_key: str | None = None
    openai_model: str = "text-embedding-3-small"
    openai_base_url: str | None = None
    #: ``provider == localhost`` — 로컬 OpenAI 호환 게이트웨이 (Ollama 등)
    localhost_base_url: str | None = None
    localhost_model: str | None = None
    localhost_api_key: str | None = None
    #: Bedrock ``bedrock-runtime`` (``AWS_REGION`` 이 비어 있으면 ``bedrock_region`` 필수)
    bedrock_region: str | None = None
    bedrock_model_id: str = "amazon.titan-embed-text-v2:0"


class AppSettings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @computed_field
    def celery_enabled(self) -> bool:
        return bool((self.celery.broker_url or "").strip())

    @property
    def embedding_dim(self) -> int:
        """레거시·``rag_models`` 등에서 쓰는 차원 — ``embedding.dim`` 과 동일."""

        return self.embedding.dim

    @property
    def local_embedding_model(self) -> str:
        """레거시 호환 — ``embedding.local_model`` 과 동일."""

        return self.embedding.local_model


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
    embedding_provider: str | None = Field(
        default=None, validation_alias=AliasChoices("EMBEDDING_PROVIDER")
    )
    embedding_dim: int | None = Field(
        default=None, validation_alias=AliasChoices("EMBEDDING_DIM")
    )
    local_embedding_model: str | None = Field(
        default=None, validation_alias=AliasChoices("LOCAL_EMBEDDING_MODEL")
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY")
    )
    openai_embedding_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_EMBEDDING_MODEL", "OPENAI_MODEL"),
    )
    openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_BASE_URL")
    )
    bedrock_region: str | None = Field(
        default=None, validation_alias=AliasChoices("BEDROCK_REGION")
    )
    bedrock_embedding_model_id: str | None = Field(
        default=None, validation_alias=AliasChoices("BEDROCK_EMBEDDING_MODEL_ID")
    )
    localhost_embedding_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("LOCALHOST_EMBEDDING_BASE_URL")
    )
    localhost_embedding_model: str | None = Field(
        default=None, validation_alias=AliasChoices("LOCALHOST_EMBEDDING_MODEL")
    )
    localhost_embedding_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("LOCALHOST_EMBEDDING_API_KEY")
    )
    # Auth bootstrap
    mcper_auth_enabled: str | None = Field(
        default=None, validation_alias=AliasChoices("MCPER_AUTH_ENABLED")
    )
    auth_secret_key: str | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_SECRET_KEY")
    )
    auth_token_expire_minutes: int | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_TOKEN_EXPIRE_MINUTES")
    )
    auth_google_client_id: str | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_GOOGLE_CLIENT_ID")
    )
    auth_google_client_secret: str | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_GOOGLE_CLIENT_SECRET")
    )
    auth_github_client_id: str | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_GITHUB_CLIENT_ID")
    )
    auth_github_client_secret: str | None = Field(
        default=None, validation_alias=AliasChoices("AUTH_GITHUB_CLIENT_SECRET")
    )
    csrf_cookie_secure: str | None = Field(
        default=None, validation_alias=AliasChoices("CSRF_COOKIE_SECURE")
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


def _normalize_legacy_embedding_keys(data: dict[str, Any]) -> None:
    """예전 최상위 ``embedding_dim`` / ``local_embedding_model`` 을 ``embedding`` 블록으로 합친다."""

    emb = data.get("embedding")
    if not isinstance(emb, dict):
        emb = {}
    if "dim" not in emb and "embedding_dim" in data:
        emb["dim"] = data["embedding_dim"]
    if "local_model" not in emb and "local_embedding_model" in data:
        emb["local_model"] = data["local_embedding_model"]
    data["embedding"] = emb


def expand_env_placeholders(obj: Any) -> Any:
    """YAML 로드 직후, 문자열 안의 ``${VAR}`` / ``${VAR:-def}`` 를 os.environ 으로 치환."""
    if isinstance(obj, str):
        return _expand_env_in_str(obj)
    if isinstance(obj, dict):
        return {k: expand_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_placeholders(v) for v in obj]
    return obj


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """중첩 dict 는 재귀 병합; 나머지는 overlay 가 덮어씀."""
    out: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    return loaded if isinstance(loaded, dict) else {}


def _load_yaml_config_data() -> dict[str, Any]:
    """explicit MCPER_CONFIG 또는 config.yaml + config.<env>.yaml 병합."""
    raw = (os.environ.get("MCPER_CONFIG") or os.environ.get("MCPER_CONFIG_PATH") or "").strip()
    root = _repo_root()
    if raw:
        explicit = Path(raw)
        if not explicit.is_file():
            raise FileNotFoundError(
                f"MCPER_CONFIG/MCPER_CONFIG_PATH points to missing file: {explicit}"
            )
        return _load_yaml_dict(explicit)

    data = _load_yaml_dict(root / "config.yaml")
    env_name = (os.environ.get("MCPER_ENV") or os.environ.get("APP_ENV") or "").strip()
    if env_name:
        overlay = _load_yaml_dict(root / f"config.{env_name}.yaml")
        if overlay:
            data = _deep_merge_dict(data, overlay)
    return data


def load_settings() -> AppSettings:
    data = _load_yaml_config_data()
    data = expand_env_placeholders(data)
    _normalize_legacy_embedding_keys(data)

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

    if env.embedding_provider:
        p = env.embedding_provider.strip().lower()
        if p in ("local", "openai", "localhost", "bedrock"):
            cfg.embedding = cfg.embedding.model_copy(update={"provider": p})
    if env.embedding_dim is not None:
        cfg.embedding.dim = env.embedding_dim
    if env.local_embedding_model:
        cfg.embedding.local_model = env.local_embedding_model
    if env.openai_api_key:
        cfg.embedding.openai_api_key = env.openai_api_key
    if env.openai_embedding_model:
        cfg.embedding.openai_model = env.openai_embedding_model
    if env.openai_base_url:
        cfg.embedding.openai_base_url = env.openai_base_url.strip()
    if env.bedrock_region:
        cfg.embedding.bedrock_region = env.bedrock_region.strip()
    if env.bedrock_embedding_model_id:
        cfg.embedding.bedrock_model_id = env.bedrock_embedding_model_id.strip()
    if env.localhost_embedding_base_url:
        cfg.embedding.localhost_base_url = env.localhost_embedding_base_url.strip()
    if env.localhost_embedding_model:
        cfg.embedding.localhost_model = env.localhost_embedding_model.strip()
    if env.localhost_embedding_api_key:
        cfg.embedding.localhost_api_key = env.localhost_embedding_api_key.strip()

    # Auth settings override
    if env.mcper_auth_enabled is not None:
        v = env.mcper_auth_enabled.strip().lower()
        cfg.auth.enabled = v in ("1", "true", "yes")
    if env.auth_secret_key:
        cfg.auth.secret_key = env.auth_secret_key
    if env.auth_token_expire_minutes is not None:
        cfg.auth.token_expire_minutes = env.auth_token_expire_minutes
    if env.auth_google_client_id:
        cfg.auth.google_client_id = env.auth_google_client_id
    if env.auth_google_client_secret:
        cfg.auth.google_client_secret = env.auth_google_client_secret
    if env.auth_github_client_id:
        cfg.auth.github_client_id = env.auth_github_client_id
    if env.auth_github_client_secret:
        cfg.auth.github_client_secret = env.auth_github_client_secret
    if env.csrf_cookie_secure is not None:
        v = env.csrf_cookie_secure.strip().lower()
        cfg.security.secure_cookie = v in ("1", "true", "yes")

    return cfg


# 프로세스당 한 번 로드 (필요 시 테스트에서 재할당)
settings: AppSettings = load_settings()
