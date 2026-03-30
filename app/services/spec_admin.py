"""Helpers for admin specification (spec) views."""

from __future__ import annotations

import json
import re

from app.db.models import Spec


def spec_display_title(row: Spec) -> str:
    t = (row.title or "").strip()
    if t:
        return t
    return f"Specification #{row.id}"


def content_looks_like_vector_or_blob(content: str) -> bool:
    """
    Returns True if content appears to be vector embedding or binary-like.
    In UI, only title is highlighted and content body is hidden.
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
