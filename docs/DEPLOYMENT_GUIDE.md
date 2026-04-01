# 배포 가이드

**저장소**: stz-game-service

## 배포 체크리스트

### Pre-Deployment
- [ ] 모든 테스트 통과 (`pytest`)
- [ ] 린트 확인 (`ruff check`)
- [ ] DB 마이그레이션 준비 완료
- [ ] 환경 변수 설정 완료

### Deployment
- [ ] 최신 코드 pull
- [ ] 의존성 설치 (`pip install -r requirements.txt`)
- [ ] 마이그레이션 실행 (`alembic upgrade head`)
- [ ] 서비스 재시작

### Post-Deployment
- [ ] 헬스 체크 (`/health`)
- [ ] 모니터링 대시보드 확인 (Grafana)
- [ ] 로그 모니터링 (Datadog)
- [ ] 에러 알림 설정

## 배포 환경

| 환경 | URL | 용도 |
|------|-----|------|
| **Dev** | dev.example.com | 개발/테스트 |
| **Staging** | staging.example.com | 사전 검증 |
| **Production** | api.example.com | 실운영 |

## 롤백 절차

```bash
# 1. 이전 버전 확인
git log --oneline | head -5

# 2. 이전 버전으로 복구
git revert <commit-hash>

# 3. 재배포
# (위 배포 절차 반복)
```
