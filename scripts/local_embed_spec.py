#!/usr/bin/env python3
"""워커 큐를 거치지 않고 로컬에서 기획서(spec) 청크 임베딩 후 DB에 반영.

``DATABASE_URL`` (또는 앱과 동일한 config) 이 있어야 하며, 서버와 **동일한**
``EMBEDDING_DIM`` / ``LOCAL_EMBEDDING_MODEL`` (또는 ``embedding.dim`` / ``embedding`` 블록)을 써야 검색이 일치한다.

예::

  cd /path/to/mcper
  export DATABASE_URL=postgresql://...
  python scripts/local_embed_spec.py 42

MCP 경유로 하려면 ``push_spec_chunks_with_embeddings`` 툴을 쓰면 된다
(``docs/LOCAL_EMBEDDING_FALLBACK.md``).
"""

from __future__ import annotations

import argparse
import os
import sys


def _bootstrap_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> int:
    _bootstrap_path()

    p = argparse.ArgumentParser(description="Index one spec_id with local embeddings (no Celery).")
    p.add_argument("spec_id", type=int, help="specs.id")
    args = p.parse_args()

    if not (os.environ.get("DATABASE_URL") or "").strip():
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    from app.db.database import SessionLocal
    from app.services.spec_indexing import index_spec_synchronously

    db = SessionLocal()
    try:
        out = index_spec_synchronously(db, args.spec_id)
        print(out)
        return 0 if out.get("ok") else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
