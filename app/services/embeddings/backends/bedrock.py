"""AWS Bedrock 백엔드."""

import json
import logging
import os

from app.config import EmbeddingSettings
from .utils import norm_inputs

logger = logging.getLogger(__name__)


def _bedrock_body(model_id: str, text: str, dim: int) -> str:
    if "embed-text-v2" in model_id or "titan-embed-text-v2" in model_id:
        return json.dumps(
            {"inputText": text, "dimensions": dim, "normalize": True},
            ensure_ascii=False,
        )
    return json.dumps({"inputText": text}, ensure_ascii=False)


class BedrockBackend:
    """AWS Bedrock ``bedrock-runtime`` ``invoke_model``."""

    def __init__(self, cfg: EmbeddingSettings) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Bedrock 임베딩: pip install boto3 가 필요합니다") from exc

        region = (
            cfg.bedrock_region
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
        )
        if not region:
            raise RuntimeError(
                "Bedrock: embedding.bedrock_region 또는 AWS_REGION / AWS_DEFAULT_REGION 필요"
            )
        self._cfg = cfg
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model_id = self._cfg.bedrock_model_id
        dim = self._cfg.dim
        out: list[list[float]] = []
        for t in norm_inputs(texts):
            body = _bedrock_body(model_id, t, dim)
            resp = self._client.invoke_model(
                modelId=model_id,
                body=body.encode("utf-8"),
                contentType="application/json",
                accept="application/json",
            )
            raw = resp["body"].read()
            payload = json.loads(raw)
            emb = payload.get("embedding")
            if not isinstance(emb, list):
                raise RuntimeError("Bedrock 응답에 embedding 배열이 없습니다")
            out.append([float(x) for x in emb])
        return out
