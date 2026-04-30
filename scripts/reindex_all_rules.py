#!/usr/bin/env python3
"""Re-index all existing rule versions into rule_chunks.

Usage:
    docker compose exec web python scripts/reindex_all_rules.py
    docker compose exec web python scripts/reindex_all_rules.py --purge-old

Options:
    --purge-old    Delete all rows from rule_chunks first, then reindex.
                   Useful when chunks from older versions have accumulated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.embeddings import configure_embedding_backend  # noqa: E402

configure_embedding_backend(settings.embedding)

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.rag_models import RuleChunk  # noqa: E402
from app.db.rule_models import AppRuleVersion, GlobalRuleVersion, RepoRuleVersion  # noqa: E402
from app.rule.service import make_default_rule_service  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402


def _latest_versions(db, model, group_cols):
    """Get latest version rows for each group."""
    subq = (
        select(
            *[getattr(model, c).label(c) for c in group_cols],
            func.max(model.version).label("mv"),
        )
        .group_by(*[getattr(model, c) for c in group_cols])
        .subquery()
    )
    conditions = [getattr(model, c) == subq.c[c] for c in group_cols]
    conditions.append(model.version == subq.c.mv)
    return (
        db.scalars(select(model).join(subq, *conditions)).all()
        if len(conditions) == 1
        else (
            db.scalars(
                select(model).join(
                    subq,
                    conditions[0] & conditions[1]
                    if len(conditions) == 2
                    else conditions[0] & conditions[1] & conditions[2],
                )
            ).all()
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Reindex all rule versions into rule_chunks."
    )
    parser.add_argument(
        "--purge-old",
        action="store_true",
        help="Delete all existing rule_chunks rows before reindexing (one-time cleanup).",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    if args.purge_old:
        deleted = db.execute(delete(RuleChunk)).rowcount
        db.commit()
        print(f"[purge-old] Deleted {deleted} rows from rule_chunks")

    svc = make_default_rule_service(db)
    total = 0
    errors = 0

    # Global rules
    global_rows = _latest_versions(db, GlobalRuleVersion, ["section_name"])
    for row in global_rows:
        try:
            result = svc.index_rule(
                "global",
                row.id,
                row.body,
                domain=row.domain,
                section_name=row.section_name,
            )
            if result.ok:
                total += 1
                print(
                    f"  global/{row.section_name} v{row.version} -> {result.child_count} children"
                )
            else:
                errors += 1
                print(f"  FAIL global/{row.section_name}: {result.error}")
        except Exception as exc:
            errors += 1
            print(f"  ERROR global/{row.section_name}: {exc}")

    # App rules
    app_rows = _latest_versions(db, AppRuleVersion, ["app_name", "section_name"])
    for row in app_rows:
        try:
            result = svc.index_rule(
                "app",
                row.id,
                row.body,
                app_name=row.app_name,
                domain=row.domain,
                section_name=row.section_name,
            )
            if result.ok:
                total += 1
                print(
                    f"  app/{row.app_name}/{row.section_name} v{row.version} -> {result.child_count} children"
                )
            else:
                errors += 1
                print(f"  FAIL app/{row.app_name}/{row.section_name}: {result.error}")
        except Exception as exc:
            errors += 1
            print(f"  ERROR app/{row.app_name}/{row.section_name}: {exc}")

    # Repo rules
    repo_rows = _latest_versions(db, RepoRuleVersion, ["pattern", "section_name"])
    for row in repo_rows:
        try:
            result = svc.index_rule(
                "repo",
                row.id,
                row.body,
                pattern=row.pattern,
                domain=row.domain,
                section_name=row.section_name,
            )
            if result.ok:
                total += 1
                pat = row.pattern or "(default)"
                print(
                    f"  repo/{pat}/{row.section_name} v{row.version} -> {result.child_count} children"
                )
            else:
                errors += 1
                print(f"  FAIL repo/{row.pattern}/{row.section_name}: {result.error}")
        except Exception as exc:
            errors += 1
            print(f"  ERROR repo/{row.pattern}/{row.section_name}: {exc}")

    db.close()
    print(f"\nDone. Indexed: {total}, Errors: {errors}")


if __name__ == "__main__":
    main()
