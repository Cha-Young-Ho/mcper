#!/usr/bin/env python3
"""
구조적 제약 검증 (Harness Engineering)

의존성 계층 순서 검증:
  Types → Config → Repo → Service → Runtime → UI

위반 사항을 찾으면 에러 반환.
"""

import ast
import sys
from pathlib import Path
from typing import Set, Tuple

# 계층 정의
LAYERS = {
    "types": {"app/models/", "app/schemas/"},
    "config": {"app/config.py"},
    "repo": {"app/db/"},
    "service": {"app/services/", "app/auth/service.py"},
    "runtime": {"app/worker/", "app/asgi/"},
    "ui": {"app/routers/", "app/templates/"},
}

LAYER_ORDER = ["types", "config", "repo", "service", "runtime", "ui"]


def get_layer(filepath: str) -> str:
    """파일이 어느 계층에 속하는지 판단."""
    for layer, patterns in LAYERS.items():
        for pattern in patterns:
            if pattern in filepath:
                return layer
    return None


def parse_imports(filepath: str) -> Set[str]:
    """파일에서 import하는 모듈 목록 추출."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        return imports
    except:
        return set()


def check_violations() -> list:
    """계층 위반 사항 검색."""
    violations = []
    app_dir = Path("app")

    for py_file in app_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        source_layer = get_layer(str(py_file))
        if not source_layer:
            continue

        imports = parse_imports(str(py_file))
        source_idx = LAYER_ORDER.index(source_layer)

        for imp in imports:
            # "app.xxx" import 필터링
            if not imp.startswith("app."):
                continue

            target_path = imp.replace(".", "/")
            target_layer = None

            for layer, patterns in LAYERS.items():
                for pattern in patterns:
                    if target_path.startswith(pattern.replace("/", "").split("app")[1]):
                        target_layer = layer
                        break

            if target_layer and target_layer in LAYER_ORDER:
                target_idx = LAYER_ORDER.index(target_layer)
                if target_idx < source_idx:
                    # 역방향 의존성 (위반)
                    violations.append({
                        "file": str(py_file),
                        "layer": source_layer,
                        "imports": imp,
                        "target_layer": target_layer,
                    })

    return violations


if __name__ == "__main__":
    violations = check_violations()

    if violations:
        print("❌ 의존성 계층 위반 발견:")
        for v in violations:
            print(f"  {v['file']} ({v['layer']}) → {v['target_layer']}")
        sys.exit(1)
    else:
        print("✅ 의존성 계층 검증 통과")
        sys.exit(0)
