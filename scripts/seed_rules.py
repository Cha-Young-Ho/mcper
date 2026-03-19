#!/usr/bin/env python3
"""Seed MCP rule tables from bundled defaults. Run from repo root."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.seed_defaults import seed_force, seed_if_empty, seed_repo_if_empty  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(
        description="Seed global_rule_versions / repo_rule_versions / app_rule_versions from defaults"
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Delete all rule rows and re-insert defaults from app/prompts + built-in app/repo snippets",
    )
    args = p.parse_args()
    init_db()
    db = SessionLocal()
    try:
        if args.force:
            seed_force(db)
            print("Force re-seed completed.")
        elif seed_if_empty(db):
            print("Seeded (DB had no global rows).")
        elif seed_repo_if_empty(db):
            print("Repository rules backfilled (global existed, repo was empty).")
        else:
            print("Skipped: rules already present. Use --force to wipe and re-seed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
