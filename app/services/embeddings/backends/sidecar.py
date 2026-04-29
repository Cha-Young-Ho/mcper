"""HTTP sidecar 기반 임베딩 백엔드.

Phase 3 (C안): 384d sentence-transformers 를 별도 컨테이너 (`infra/docker/embed-sidecar`)
로 격리하고, 웹·워커 프로세스는 HTTP 로만 임베딩을 요청한다. 각 인스턴스가 500MB
모델을 중복 로드하던 문제 해결 — pgvector/HNSW 호환을 위해 차원은 기존 384 유지.

- 엔드포인트: POST {url}/embed  {"texts": [...]}
- 응답: {"model": str, "dim": int, "vectors": [[...]]}
"""

from __future__ import annotations

import httpx

from .utils import norm_inputs


class SidecarEmbeddingBackend:
    """Sidecar HTTP 서비스를 통한 임베딩 클라이언트.

    본체 `EmbeddingBackend` 프로토콜을 만족하려면 ``embed_texts`` 만 구현하면 된다.
    """

    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._endpoint}/embed"
        r = self._client.post(url, json={"texts": norm_inputs(texts)})
        r.raise_for_status()
        data = r.json()
        vectors = data.get("vectors") or []
        return [[float(x) for x in v] for v in vectors]

    def close(self) -> None:
        self._client.close()
