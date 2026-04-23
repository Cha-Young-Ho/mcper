#!/usr/bin/env python3
"""Seed adventure harness from actual local files.

Reads every .md file from the stz-game-service/adventure harness
and uploads them as-is to MCP (skills + rules).

Run inside Docker:
    docker compose exec web python scripts/seed_adventure_from_files.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import init_db, SessionLocal  # noqa: E402
from app.services.versioned_skills import (  # noqa: E402
    publish_global_skill,
    publish_app_skill,
    publish_repo_skill,
)
from app.services.versioned_rules import publish_app, publish_repo  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_NAME = "adventure"
REPO_PATTERN = "stz-game-service"

# In Docker the host is mounted at /app, but the adventure repo is separate.
# We'll look for it via environment or a known path.
# Since Docker mounts mcper repo at /app, the adventure files won't be there.
# So we embed the file reading logic to work on the HOST side.
# This script is designed to run on the HOST, not inside Docker.

# Actually, let's make it flexible:
ADVENTURE_ROOT = None
for candidate in [
    Path("/adventure"),  # Docker mount
    Path("/Users/wemadeplay/stz-game-service/adventure"),  # host macOS
    Path.home() / "stz-game-service" / "adventure",  # generic home
]:
    if candidate.exists():
        ADVENTURE_ROOT = candidate
        break

if ADVENTURE_ROOT is None:
    print("ERROR: Cannot find stz-game-service/adventure directory")
    sys.exit(1)

CLAUDE_ROOT = ADVENTURE_ROOT / ".claude"

# ---------------------------------------------------------------------------
# File registry: path -> (type, scope, section_name)
# type: "skill" | "rule"
# scope: "app" | "repo"
# ---------------------------------------------------------------------------

def build_registry() -> list[dict]:
    """Build file registry from actual filesystem."""
    registry = []

    # 1. Root CLAUDE.md -> app skill
    claude_md = ADVENTURE_ROOT / "CLAUDE.md"
    if claude_md.exists():
        registry.append({
            "path": "CLAUDE.md",
            "file": claude_md,
            "type": "skill",
            "scope": "app",
            "section": "claude-md",
        })

    # 2. .claude/AGENTS.md -> app skill
    agents_md = CLAUDE_ROOT / "AGENTS.md"
    if agents_md.exists():
        registry.append({
            "path": ".claude/AGENTS.md",
            "file": agents_md,
            "type": "skill",
            "scope": "app",
            "section": "agents-index",
        })

    # 3. .claude/ARCHITECTURE.md -> repo skill (프로젝트 구조는 레포 공통)
    arch_md = CLAUDE_ROOT / "ARCHITECTURE.md"
    if arch_md.exists():
        registry.append({
            "path": ".claude/ARCHITECTURE.md",
            "file": arch_md,
            "type": "skill",
            "scope": "repo",
            "section": "architecture",
        })

    # 4. .claude/agents/*.md -> app skill (agent-{name})
    agents_dir = CLAUDE_ROOT / "agents"
    if agents_dir.is_dir():
        for f in sorted(agents_dir.glob("*.md")):
            registry.append({
                "path": f".claude/agents/{f.name}",
                "file": f,
                "type": "skill",
                "scope": "app",
                "section": f"agent-{f.stem}",
            })

    # 5. .claude/skills/*/skill.md -> app skill ({skill-name})
    skills_dir = CLAUDE_ROOT / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "skill.md"
                if skill_file.exists():
                    registry.append({
                        "path": f".claude/skills/{skill_dir.name}/skill.md",
                        "file": skill_file,
                        "type": "skill",
                        "scope": "app",
                        "section": skill_dir.name,
                    })

    # 6. .claude/docs/*.md -> app skill (doc-{name})
    docs_dir = CLAUDE_ROOT / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.glob("*.md")):
            registry.append({
                "path": f".claude/docs/{f.name}",
                "file": f,
                "type": "skill",
                "scope": "app",
                "section": f"doc-{f.stem.lower()}",
            })

    # 7. .claude/docs/references/*.md -> app skill (ref-{name})
    refs_dir = CLAUDE_ROOT / "docs" / "references"
    if refs_dir.is_dir():
        for f in sorted(refs_dir.glob("*.md")):
            registry.append({
                "path": f".claude/docs/references/{f.name}",
                "file": f,
                "type": "skill",
                "scope": "app",
                "section": f"ref-{f.stem.lower()}",
            })

    # 8. .claude/docs/patterns/*.md -> app skill (pattern-{name})
    patterns_dir = CLAUDE_ROOT / "docs" / "patterns"
    if patterns_dir.is_dir():
        for f in sorted(patterns_dir.glob("*.md")):
            registry.append({
                "path": f".claude/docs/patterns/{f.name}",
                "file": f,
                "type": "skill",
                "scope": "app",
                "section": f"pattern-{f.stem.lower()}",
            })

    # 9. .claude/docs/workflow/*.md -> repo skill (workflow-{name})
    #    워크플로우는 레포 공통
    workflow_dir = CLAUDE_ROOT / "docs" / "workflow"
    if workflow_dir.is_dir():
        for f in sorted(workflow_dir.glob("*.md")):
            registry.append({
                "path": f".claude/docs/workflow/{f.name}",
                "file": f,
                "type": "skill",
                "scope": "repo",
                "section": f"workflow-{f.stem.lower()}",
            })

    # 10. .claude/docs/exec-plans/**/*.md -> app skill (exec-{name})
    exec_dir = CLAUDE_ROOT / "docs" / "exec-plans"
    if exec_dir.is_dir():
        for f in sorted(exec_dir.rglob("*.md")):
            rel = f.relative_to(exec_dir)
            section = f"exec-{'-'.join(rel.with_suffix('').parts).lower()}"
            registry.append({
                "path": f".claude/docs/exec-plans/{rel}",
                "file": f,
                "type": "skill",
                "scope": "app",
                "section": section,
            })

    # 11. .claude/rules/*.md -> app rule ({name})
    rules_dir = CLAUDE_ROOT / "rules"
    if rules_dir.is_dir():
        for f in sorted(rules_dir.glob("*.md")):
            registry.append({
                "path": f".claude/rules/{f.name}",
                "file": f,
                "type": "rule",
                "scope": "app",
                "section": f.stem.lower(),
            })

    return registry


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    init_db()
    db = SessionLocal()

    registry = build_registry()

    print("=" * 60)
    print(f"adventure 하네스 원본 파일 시딩")
    print(f"소스: {ADVENTURE_ROOT}")
    print(f"파일 수: {len(registry)}")
    print("=" * 60)

    app_skills = 0
    repo_skills = 0
    app_rules = 0
    errors = []

    try:
        for entry in registry:
            path = entry["path"]
            try:
                content = entry["file"].read_text(encoding="utf-8").replace("\r\n", "\n")
                if not content.strip():
                    errors.append(f"  ⚠ empty: {path}")
                    continue

                ftype = entry["type"]
                scope = entry["scope"]
                section = entry["section"]

                if ftype == "rule":
                    _, sn, v = publish_app(db, APP_NAME, content, section)
                    print(f"  ✓ [rule/app] {section} v{v} ← {path}")
                    app_rules += 1
                elif scope == "repo":
                    _, sn, v = publish_repo_skill(db, REPO_PATTERN, content, section)
                    print(f"  ✓ [skill/repo] {section} v{v} ← {path}")
                    repo_skills += 1
                else:
                    _, sn, v = publish_app_skill(db, APP_NAME, content, section)
                    print(f"  ✓ [skill/app] {section} v{v} ← {path}")
                    app_skills += 1

            except Exception as exc:
                errors.append(f"  ✗ {path}: {exc}")

        print("\n" + "=" * 60)
        print("시딩 완료!")
        print("=" * 60)
        print(f"\n  App Skills:  {app_skills}개")
        print(f"  Repo Skills: {repo_skills}개")
        print(f"  App Rules:   {app_rules}개")
        print(f"  총: {app_skills + repo_skills + app_rules}개")

        if errors:
            print(f"\n  에러 {len(errors)}건:")
            for e in errors:
                print(f"    {e}")

        # Also re-seed global skills (these are project-agnostic)
        print("\n--- Global Skills (재등록) ---")
        from scripts.seed_adventure_data import (
            GLOBAL_SKILL_MCP_USAGE,
            GLOBAL_SKILL_HARNESS_CONSTRUCTION,
        )
        v = publish_global_skill(db, GLOBAL_SKILL_MCP_USAGE, "mcp-usage")
        print(f"  ✓ global/mcp-usage v{v}")
        v = publish_global_skill(db, GLOBAL_SKILL_HARNESS_CONSTRUCTION, "harness-construction")
        print(f"  ✓ global/harness-construction v{v}")

    except Exception as exc:
        db.rollback()
        print(f"\n❌ 에러: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
