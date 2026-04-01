#!/usr/bin/env python3
"""
로컬 문서(docs/*.md)를 MCP DB의 Rule로 저장

용도:
- stz-game-service Repository Rule 생성
- 로컬 가이드를 sectioned rule로 변환
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.database import SessionLocal
from app.services.versioned_rules import publish_repo
import os

# 환경변수 로드 (docker compose의 .env.local과 동일)
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@127.0.0.1:5433/mcpdb")
os.environ.setdefault("DB_NAME", "mcpdb")
os.environ.setdefault("DB_USER", "user")
os.environ.setdefault("DB_PASSWORD", "changeme_strong_password")


def load_markdown_files():
    """로컬 docs 디렉터리에서 .md 파일 로드"""
    docs_dir = project_root / "docs"

    rules = {
        "COMMIT_GUIDE.md": {
            "section": "commit",
            "pattern": "stz-game-service",
        },
        "DEPLOYMENT_GUIDE.md": {
            "section": "deployment",
            "pattern": "stz-game-service",
        },
        "CODE_STYLE.md": {
            "section": "code_style",
            "pattern": "stz-game-service",
        },
        "PLANS.md": {
            "section": "planning",
            "pattern": "stz-game-service",
        },
        "DESIGN.md": {
            "section": "design",
            "pattern": "stz-game-service",
        },
        "SECURITY.md": {
            "section": "security",
            "pattern": "stz-game-service",
        },
        "RELIABILITY.md": {
            "section": "reliability",
            "pattern": "stz-game-service",
        },
    }

    results = []
    for filename, meta in rules.items():
        filepath = docs_dir / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                body = f.read()
            results.append({
                "filename": filename,
                "section": meta["section"],
                "pattern": meta["pattern"],
                "body": body,
            })
            print(f"✅ 로드: {filename}")
        else:
            print(f"⚠️ 없음: {filename}")

    return results


def publish_to_db(rules):
    """DB의 RepoRuleVersion에 저장"""
    session = SessionLocal()
    try:
        for rule in rules:
            pattern, section, version = publish_repo(
                session,
                pattern=rule["pattern"],
                body=rule["body"],
                section_name=rule["section"],
                sort_order=100,
            )
            print(f"📝 저장: {rule['filename']} → repo_rule_versions")
            print(f"   pattern={pattern}, section={section}, version={version}")
    finally:
        session.close()


def main():
    print("=" * 60)
    print("로컬 문서 → MCP Rule DB 마이그레이션")
    print("=" * 60)

    # 1. 문서 로드
    print("\n[Step 1] 로컬 문서 로드...")
    rules = load_markdown_files()
    print(f"총 {len(rules)}개 문서 로드\n")

    # 2. DB 저장
    print("[Step 2] MCP Rule DB에 저장...")
    publish_to_db(rules)

    print("\n" + "=" * 60)
    print("✅ 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
