"""Unit tests for `app.services.embeddings` — 백엔드 팩토리 + sidecar/OpenAI HTTP client.

HTTP/boto3 모두 mock. 네트워크·모델 다운로드 없이 URL 구성·요청 본문·에러 분기를 검증.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.config import EmbeddingSettings
from app.services.embeddings.backends.sidecar import SidecarEmbeddingBackend
from app.services.embeddings.backends.utils import norm_inputs
from app.services.embeddings.factory import build_embedding_backend


# ── norm_inputs ─────────────────────────────────────────────────────


class TestNormInputs:
    def test_preserves_non_empty(self):
        assert norm_inputs(["a", "bc"]) == ["a", "bc"]

    def test_replaces_empty_with_space(self):
        # pgvector HNSW 안정성을 위해 빈 문자열을 단일 공백으로 치환.
        assert norm_inputs(["", "x"]) == [" ", "x"]

    def test_replaces_whitespace_only(self):
        assert norm_inputs(["   ", "\n", "y"]) == [" ", " ", "y"]


# ── build_embedding_backend (factory) ───────────────────────────────


class TestBuildEmbeddingBackend:
    def test_openai_requires_api_key(self):
        cfg = EmbeddingSettings(provider="openai", openai_api_key=None)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(RuntimeError, match="OpenAI"):
                build_embedding_backend(cfg)

    def test_openai_strips_trailing_slash_on_base_url(self):
        cfg = EmbeddingSettings(
            provider="openai",
            openai_api_key="sk-test",
            openai_base_url="https://api.example.com/v1/",
        )
        backend = build_embedding_backend(cfg)
        # 내부 속성 이름(_base) 으로 rstrip 확인.
        assert backend._base == "https://api.example.com/v1"
        assert backend._api_key == "sk-test"

    def test_localhost_requires_model(self):
        cfg = EmbeddingSettings(
            provider="localhost",
            localhost_model=None,
        )
        with pytest.raises(RuntimeError, match="localhost"):
            build_embedding_backend(cfg)

    def test_sidecar_env_var_overrides_config(self):
        cfg = EmbeddingSettings(provider="sidecar", sidecar_url="http://cfg:8000")
        with patch.dict(
            os.environ, {"EMBEDDING_SIDECAR_URL": "http://override:9000"}, clear=False
        ):
            backend = build_embedding_backend(cfg)
            assert isinstance(backend, SidecarEmbeddingBackend)
            assert backend._endpoint == "http://override:9000"

    def test_unknown_provider_raises(self):
        # 런타임 에러 회귀 방지용 — provider Literal 검증을 우회해 강제 주입.
        cfg = EmbeddingSettings()
        object.__setattr__(cfg, "provider", "bogus")
        with pytest.raises(RuntimeError, match="알 수 없는"):
            build_embedding_backend(cfg)


# ── SidecarEmbeddingBackend ─────────────────────────────────────────


class TestSidecarBackend:
    def test_empty_list_returns_empty_without_http_call(self):
        backend = SidecarEmbeddingBackend("http://embed:8000")
        # httpx 클라이언트를 mock 으로 교체해 실제 요청이 가지 않음을 보장.
        backend._client = MagicMock()
        out = backend.embed_texts([])
        assert out == []
        backend._client.post.assert_not_called()

    def test_posts_to_normalized_endpoint_and_parses_vectors(self):
        backend = SidecarEmbeddingBackend("http://embed:8000/")  # trailing slash
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "model": "all-MiniLM-L6-v2",
            "dim": 3,
            "vectors": [[1, 2, 3], [4, 5, 6]],
        }
        fake_client = MagicMock()
        fake_client.post.return_value = fake_resp
        backend._client = fake_client

        out = backend.embed_texts(["hello", ""])
        # trailing slash 는 제거 → /embed 엔드포인트 조립.
        assert backend._endpoint == "http://embed:8000"
        args, kwargs = fake_client.post.call_args
        assert args[0] == "http://embed:8000/embed"
        # 빈 문자열은 공백으로 정규화되어 요청 본문에 실림.
        assert kwargs["json"] == {"texts": ["hello", " "]}
        # 반환은 float 리스트.
        assert out == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    def test_missing_vectors_field_returns_empty_list(self):
        backend = SidecarEmbeddingBackend("http://embed:8000")
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"model": "x", "dim": 3}  # no 'vectors'
        fake_client = MagicMock()
        fake_client.post.return_value = fake_resp
        backend._client = fake_client

        assert backend.embed_texts(["a"]) == []

    def test_http_error_propagates(self):
        backend = SidecarEmbeddingBackend("http://embed:8000")
        fake_resp = MagicMock()
        fake_resp.raise_for_status.side_effect = RuntimeError("500 Server Error")
        fake_client = MagicMock()
        fake_client.post.return_value = fake_resp
        backend._client = fake_client

        with pytest.raises(RuntimeError, match="500"):
            backend.embed_texts(["a"])
