#!/usr/bin/env python3
"""Seed harness docs into specs table. Run from repo root.

Usage:
    python scripts/seed_harness_docs.py          # sync (skip unchanged)
    python scripts/seed_harness_docs.py --list    # list registered docs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import init_db  # noqa: E402
from app.tools.harness_tools import list_harness_docs_impl, sync_harness_docs_impl  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Sync MCPER harness docs to DB")
    p.add_argument("--list", action="store_true", help="List registered harness docs")
    args = p.parse_args()

    init_db()

    if args.list:
        result = json.loads(list_harness_docs_impl())
        if result.get("ok"):
            print(f"Registered harness docs: {result['count']}")
            for doc in result["docs"]:
                print(
                    f"  [{doc['scope']:>10}] {doc['title']:<35} ({doc['content_length']} chars)"
                )
        else:
            print(f"Error: {result.get('error')}")
        return

    result = json.loads(sync_harness_docs_impl())
    if result.get("ok"):
        print(
            f"Sync complete: "
            f"{result['inserted']} inserted, "
            f"{result['updated']} updated, "
            f"{result['unchanged']} unchanged"
        )
        if result.get("errors"):
            for err in result["errors"]:
                print(f"  WARNING: {err}")
    else:
        print(f"Sync failed: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
