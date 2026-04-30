"""admin 마스터 계정 비번 리셋.

사용:
    python scripts/reset_admin_password.py              # ADMIN_PASSWORD env
    python scripts/reset_admin_password.py changeme     # 인자로 직접

DB 에 이미 seed 된 admin 계정(`ADMIN_USER` / `is_admin=True`) 의 hashed_password
를 현재 ADMIN_PASSWORD (또는 인자) 로 재설정. 계정이 없으면 새로 생성.
마스터 단일 계정 운용 정책에 맞춰 기존 admin 외 모든 유저는 건드리지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.auth.service import hash_password  # noqa: E402
from app.db.auth_models import User  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402


def main() -> int:
    username = os.environ.get("ADMIN_USER", "admin")
    password = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ADMIN_PASSWORD")
    if not password:
        print("ERROR: ADMIN_PASSWORD env 또는 인자가 필요합니다.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(
                username=username,
                hashed_password=hash_password(password),
                is_admin=True,
                is_active=True,
                password_changed_at=None,
            )
            db.add(user)
            db.commit()
            print(f"created admin user: {username} (is_admin=True)")
        else:
            user.hashed_password = hash_password(password)
            user.is_admin = True
            user.is_active = True
            db.commit()
            print(f"reset password for admin user: {username}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
