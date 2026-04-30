"""``ConfigMerger`` — defaults + YAML + 환경변수 3단 병합의 단일 책임 모듈.

`app.config` 에서 분리 (Q09). 동작은 이전과 동일:

1. :meth:`load_defaults` — 베이스 dict 를 비운다 (``AppSettings`` 가 pydantic
   기본값으로 누락 필드를 채우므로 실제로는 no-op 에 가까운 훅).
2. :meth:`load_yaml` — ``MCPER_CONFIG`` (단일 파일) 또는 ``config.yaml`` +
   ``config.<env>.yaml`` 을 깊게 병합 후 ``${VAR}`` / ``${VAR:-default}`` 치환.
3. :meth:`apply_env_overrides` — ``EnvBootstrapSettings`` (pydantic-settings) 로
   읽은 표준 env 값을 병합 결과에 덮어씀.
4. :meth:`finalize` — 최종 ``AppSettings`` 인스턴스 반환.

외부에서는 ``app.config.load_settings`` 만 호출하고, 이 클래스를 직접 쓰는
경우는 테스트·디버깅 한정이다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


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


def expand_env_placeholders(obj: Any) -> Any:
    """YAML 로드 직후, 문자열 안의 ``${VAR}`` / ``${VAR:-def}`` 를 os.environ 으로 치환."""
    if isinstance(obj, str):
        return _expand_env_in_str(obj)
    if isinstance(obj, dict):
        return {k: expand_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_placeholders(v) for v in obj]
    return obj


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


def _repo_root() -> Path:
    # app/config_merger.py → 리포 루트 = 두 단계 위
    return Path(__file__).resolve().parent.parent


class ConfigMerger:
    """defaults + YAML + env 를 순서대로 병합해 ``AppSettings`` 를 생성.

    사용::

        from app.config_merger import ConfigMerger

        cfg = (
            ConfigMerger()
            .load_defaults()
            .load_yaml()
            .apply_env_overrides()
            .finalize()
        )
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._env: EnvBootstrapSettings | None = None

    # ── 1. defaults ────────────────────────────────────────────────
    def load_defaults(self) -> ConfigMerger:
        """베이스 dict 를 빈 값으로 초기화.

        ``AppSettings.model_validate`` 가 누락된 필드에 pydantic 기본값을
        적용하므로, 병합 베이스는 비어 있어도 동작이 같다. 명시적으로
        호출해 파이프라인 단계를 드러내기 위한 훅.
        """

        self._data = {}
        return self

    # ── 2. YAML ────────────────────────────────────────────────────
    def load_yaml(self, path: str | Path | None = None) -> ConfigMerger:
        """YAML 파일을 읽어 현재 dict 위에 깊게 병합.

        ``path`` 지정 시 그 파일만 로드. 미지정 시 ``MCPER_CONFIG`` /
        ``MCPER_CONFIG_PATH`` 환경변수 또는 ``config.yaml`` + ``config.<env>.yaml``
        탐색 순서를 따른다.
        """

        yaml_data = self._resolve_yaml_data(path)
        yaml_data = expand_env_placeholders(yaml_data)
        _normalize_legacy_embedding_keys(yaml_data)
        self._data = _deep_merge_dict(self._data, yaml_data)
        return self

    def _resolve_yaml_data(self, path: str | Path | None) -> dict[str, Any]:
        if path is not None:
            explicit = Path(path)
            if not explicit.is_file():
                raise FileNotFoundError(
                    f"ConfigMerger.load_yaml: missing file: {explicit}"
                )
            return _load_yaml_dict(explicit)

        raw = (
            os.environ.get("MCPER_CONFIG") or os.environ.get("MCPER_CONFIG_PATH") or ""
        ).strip()
        root = _repo_root()
        if raw:
            explicit = Path(raw)
            if not explicit.is_file():
                raise FileNotFoundError(
                    f"MCPER_CONFIG/MCPER_CONFIG_PATH points to missing file: {explicit}"
                )
            return _load_yaml_dict(explicit)

        data = _load_yaml_dict(root / "config.yaml")
        env_name = (
            os.environ.get("MCPER_ENV") or os.environ.get("APP_ENV") or ""
        ).strip()
        if env_name:
            overlay = _load_yaml_dict(root / f"config.{env_name}.yaml")
            if overlay:
                data = _deep_merge_dict(data, overlay)
        return data

    # ── 3. env overrides ───────────────────────────────────────────
    def apply_env_overrides(
        self, env: EnvBootstrapSettings | None = None
    ) -> ConfigMerger:
        """표준 환경변수를 읽어 dict 위에 덮어씀."""

        self._env = env if env is not None else EnvBootstrapSettings()
        return self

    # ── 4. finalize ────────────────────────────────────────────────
    def finalize(self) -> Any:
        """``AppSettings`` 인스턴스를 만들고, env override 를 필드에 적용."""

        from app.config import AppSettings

        cfg = AppSettings.model_validate(self._data)
        env = self._env if self._env is not None else EnvBootstrapSettings()
        self._apply_env_to_cfg(cfg, env)
        return cfg

    # ── internal: env → cfg 필드 매핑 ─────────────────────────────
    @staticmethod
    def _apply_env_to_cfg(cfg: Any, env: EnvBootstrapSettings) -> None:
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
