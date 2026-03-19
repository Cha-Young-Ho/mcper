"""Sample spec row for admin 기획서 / 기획서-코드 데모."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Spec


def seed_sample_spec_if_empty(session: Session) -> bool:
    """Return True if inserted."""
    n = session.scalar(select(func.count()).select_from(Spec)) or 0
    if n > 0:
        return False
    session.add(
        Spec(
            title="[예시] your_app_name 결제 검증 플로우",
            content=(
                "## 목적\n"
                "클라이언트가 넘긴 결제 영수증을 서버에서 PG와 대조·검증한다.\n\n"
                "## 주요 흐름\n"
                "1. `receipt_id` + `user_id` 수신\n"
                "2. `PaymentVerifyService::verify()` 호출\n"
                "3. 금액은 **원 단위 정수**만 사용 (소수 금지)\n"
                "4. 실패 시 재시도 가능 에러코드 vs 불가 분리\n\n"
                "## 비기능\n"
                "- PG 타임아웃 5s, 서킷 브레이커 옵션\n"
                "- 감사 로그에 카드번호 마스킹\n"
            ),
            app_target="your_app_name",
            base_branch="main",
            related_files=[
                "app/your_app_name/controllers/PaymentController.php",
                "app/your_app_name/services/PaymentVerifyService.php",
                "lib/common/Money.php",
            ],
        )
    )
    session.commit()
    return True
