"""임베딩 sidecar — sentence-transformers 를 별도 컨테이너에서 HTTP 로 서빙.

Phase 3 (C안): 웹 인스턴스마다 500MB 모델을 중복 로드하던 문제 해결.
프로젝트 본체 `EMBEDDING_PROVIDER=sidecar` 로 선택 시 `/embed` 호출.
"""

from __future__ import annotations

import os
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
NORMALIZE = os.environ.get("EMBED_NORMALIZE", "true").lower() in ("1", "true", "yes")

_model = SentenceTransformer(MODEL_NAME)

app = FastAPI(title="mcper embed sidecar")


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    model: str
    dim: int
    vectors: List[List[float]]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dim": _model.get_sentence_embedding_dimension(),
        "normalize": NORMALIZE,
    }


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if not req.texts:
        return EmbedResponse(model=MODEL_NAME, dim=0, vectors=[])
    # 빈 문자열은 공백으로 정규화 (본체 norm_inputs 와 동일)
    inputs = [t if (t or "").strip() else " " for t in req.texts]
    vectors = _model.encode(
        inputs,
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=NORMALIZE,
    )
    rows = [[float(x) for x in v.tolist()] for v in vectors]
    return EmbedResponse(
        model=MODEL_NAME,
        dim=len(rows[0]) if rows else 0,
        vectors=rows,
    )
