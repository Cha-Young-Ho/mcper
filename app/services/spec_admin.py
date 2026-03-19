"""Helpers for admin 기획서(spec) views."""

from __future__ import annotations

import json
import re

from app.db.models import Spec


def spec_display_title(row: Spec) -> str:
    t = (row.title or "").strip()
    if t:
        return t
    return f"기획서 #{row.id}"


def content_looks_like_vector_or_blob(content: str) -> bool:
    """
    벡터 임베딩·바이너리에 가까운 본문이면 True → UI에서는 제목만 강조하고 본문은 숨김.
    """
    if not content or not content.strip():
        return False
    s = content.strip()
    if len(s) > 8000 and s.count("\n") < 3:
        letters = sum(c.isalpha() for c in s[:4000])
        if letters < 80:
            return True
    if s[0] == "[" and s[-1] == "]":
        try:
            data = json.loads(s)
            if isinstance(data, list) and len(data) >= 16:
                head = data[:32]
                if all(isinstance(x, (int, float)) for x in head):
                    return True
        except (json.JSONDecodeError, TypeError):
            pass
    if re.match(r"^[\s\d.,eE+\-]+$", s[:500]) and len(s) > 2000:
        return True
    return False
