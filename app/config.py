"""YAML + 환경변수 부트스트랩.

우선순위: **YAML(및 ``${VAR}`` / ``${VAR:-기본값}`` 치환) < 표준 환경변수** (덮어쓰기).
``pydantic-settings`` 로 ``DATABASE_URL`` 등 표준 env 키를 검증해 읽는다.

**YAML 파일 선택**

- ``MCPER_CONFIG`` / ``MCPER_CONFIG_PATH``: 단일 YAML 경로 (지정 시 **그 파일만** 로드, 환경 병합 없음).
- 미지정 시: 리포 루트 ``config.yaml`` 을 읽고, ``MCPER_ENV`` 또는 ``APP_ENV`` 가 있으면
  ``config.<env>.yaml`` 을 **깊게 병합** (중첩 dict 는 합치고, 환경 파일 값이 우선).

MCP ``Host`` 허용 목록은 **환경변수 자동 등록** + DB(기존 행 유지); 수동 어드민 등록은 제거됨.

실제 병합 로직은 :mod:`app.config_merger.ConfigMerger` 로 분리 (Q09).
이 모듈은 스키마(``AppSettings``) 정의와 ``settings`` 싱글톤 제공만 담당한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

# 병합 유틸 재노출 (기존 테스트/외부 호환).
from app.config_merger import (
    ConfigMerger,
    EnvBootstrapSettings,
    _deep_merge_dict,
    _expand_env_in_str,
    expand_env_placeholders,
)

EmbeddingProvider = Literal["local", "openai", "localhost", "bedrock"]


class AuthSettings(BaseModel):
    """JWT 기반 세션 인증 설정. MCPER_AUTH_ENABLED=true 시 활성화."""

    enabled: bool = False
    secret_key: str = ""
    token_expire_minutes: int = 1440
    # OAuth (optional — 클라이언트 ID 설정 시 자동 활성화)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None


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


def load_settings() -> AppSettings:
    """defaults → YAML → env 3단 병합 (구현은 :class:`ConfigMerger`)."""

    return ConfigMerger().load_defaults().load_yaml().apply_env_overrides().finalize()


# 프로세스당 한 번 로드 (필요 시 테스트에서 재할당)
settings: AppSettings = load_settings()


__all__ = [
    "AppSettings",
    "AuthSettings",
    "CelerySettings",
    "ConfigMerger",
    "DatabaseSettings",
    "EmbeddingProvider",
    "EmbeddingSettings",
    "EnvBootstrapSettings",
    "McpSettings",
    "SecuritySettings",
    "ServerSettings",
    "_deep_merge_dict",
    "_expand_env_in_str",
    "expand_env_placeholders",
    "load_settings",
    "settings",
]
