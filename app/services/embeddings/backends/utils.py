"""임베딩 백엔드 공유 유틸리티."""


def norm_inputs(texts: list[str]) -> list[str]:
    """빈 텍스트를 공백으로 정규화."""
    return [t if (t or "").strip() else " " for t in texts]
