#!/usr/bin/env python3
"""
로컬 문서(docs/*.md)를 MCP DB의 Rule로 저장 (카테고리 구조)

구조:
  Rules
  ├── Global (category 내 여러 파일)
  ├── Repository (my-repo)
  │   └── category (Development, Deployment, Architecture)
  │       ├── File 1
  │       ├── File 2
  │       └── File 3
  └── App
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.database import SessionLocal
from app.services.versioned_rules import publish_repo
import os

# 환경변수 로드
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@127.0.0.1:5433/mcpdb")
os.environ.setdefault("DB_NAME", "mcpdb")
os.environ.setdefault("DB_USER", "user")
os.environ.setdefault("DB_PASSWORD", "changeme_strong_password")


def load_markdown_files():
    """로컬 docs 디렉터리에서 .md 파일 로드 (카테고리별)"""
    docs_dir = project_root / "docs"

    # 카테고리별 파일 매핑
    rules_by_category = {
        "Development": {
            "COMMIT_GUIDE.md": "커밋 컨벤션 가이드",
            "CODE_STYLE.md": "코딩 스타일 가이드",
        },
        "Deployment": {
            "DEPLOYMENT_GUIDE.md": "배포 프로세스 및 체크리스트",
            "RELIABILITY.md": "배포 후 모니터링 및 장애 대응",
        },
        "Architecture": {
            "DESIGN.md": "설계 원칙 및 아키텍처 결정",
            "PLANS.md": "Phase별 계획 및 로드맵",
        },
        "Security": {
            "SECURITY.md": "보안 정책 및 위협 모델",
        },
    }

    results = []
    for category, files in rules_by_category.items():
        for filename, description in files.items():
            filepath = docs_dir / filename
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    body = f.read()
                results.append(
                    {
                        "filename": filename,
                        "category": category,  # section_name으로 사용
                        "pattern": "my-repo",
                        "body": body,
                        "description": description,
                    }
                )
                print(f"✅ 로드: [{category}] {filename}")
            else:
                print(f"⚠️ 없음: {filename}")

    return results


def publish_to_db(rules):
    """DB의 RepoRuleVersion에 저장 (category별로 그룹핑)"""
    session = SessionLocal()
    try:
        categories = {}
        for rule in rules:
            category = rule["category"]
            if category not in categories:
                categories[category] = []
            categories[category].append(rule)

        for category, category_rules in categories.items():
            # 카테고리별 통합 body 생성
            body_parts = []
            for rule in category_rules:
                body_parts.append(f"## {rule['filename']}\n\n{rule['body']}")

            combined_body = "\n\n---\n\n".join(body_parts)

            pattern, section, version = publish_repo(
                session,
                pattern=rules[0]["pattern"],  # my-repo
                body=combined_body,
                section_name=category,  # 카테고리를 section으로
                sort_order=100,
            )
            print(f"📝 저장: [{category}] → repo_rule_versions")
            print(f"   pattern={pattern}, category={section}, version={version}")
            print(
                f"   포함 파일: {', '.join([r['filename'] for r in category_rules])}\n"
            )
    finally:
        session.close()


def main():
    print("=" * 70)
    print("로컬 문서 → MCP Rule DB 마이그레이션 (카테고리 구조)")
    print("=" * 70)

    # 1. 문서 로드
    print("\n[Step 1] 로컬 문서 로드 (카테고리별)...\n")
    rules = load_markdown_files()

    if not rules:
        print("⚠️ 로드할 문서가 없습니다.")
        return

    print(f"\n총 {len(rules)}개 문서 로드\n")

    # 2. DB 저장
    print("[Step 2] MCP Rule DB에 저장 (카테고리별 통합)...\n")
    publish_to_db(rules)

    print("=" * 70)
    print("✅ 완료!")
    print("=" * 70)
    print("\n📍 DB 구조:")
    print("   Rules > Repository (my-repo) > Category")
    print("   ├── Development (COMMIT_GUIDE, CODE_STYLE)")
    print("   ├── Deployment (DEPLOYMENT_GUIDE, RELIABILITY)")
    print("   ├── Architecture (DESIGN, PLANS)")
    print("   └── Security (SECURITY)\n")


if __name__ == "__main__":
    main()
