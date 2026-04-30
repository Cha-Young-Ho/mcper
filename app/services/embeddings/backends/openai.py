"""OpenAI 호환 API 백엔드."""

import httpx

from .utils import norm_inputs


class OpenAICompatibleBackend:
    """OpenAI ``/v1/embeddings`` 호환 API (공식 OpenAI·로컬 게이트웨이 공통)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        dim: int,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = (api_key or "").strip() or None
        self._model = model
        self._dim = dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._base}/embeddings"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        out: list[list[float]] = []
        batch = 100
        inputs = norm_inputs(texts)
        with httpx.Client(timeout=120.0) as client:
            for i in range(0, len(inputs), batch):
                chunk = inputs[i : i + batch]
                body: dict = {"model": self._model, "input": chunk}
                if self._model.startswith("text-embedding-3"):
                    body["dimensions"] = self._dim
                r = client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                rows = data.get("data") or []
                rows.sort(key=lambda x: int(x.get("index", 0)))
                for row in rows:
                    emb = row.get("embedding")
                    if not isinstance(emb, list):
                        raise RuntimeError(
                            "OpenAI 호환 응답에 embedding 배열이 없습니다"
                        )
                    out.append([float(x) for x in emb])
        return out
