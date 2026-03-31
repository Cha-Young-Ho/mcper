# STZ-MCP 현황 분석 & 엔터프라이즈 로드맵
> 작성일: 2026-03-31 | 작성: @pm + @senior + @infra + @planner

---

## 목차
1. [현재 상태 체크](#1-현재-상태-체크)
2. [수정이 필요한 항목들](#2-수정이-필요한-항목들)
3. [배포 환경 전략 (dev → stage → prod)](#3-배포-환경-전략)
4. [설정 파일 해설](#4-설정-파일-해설)
5. [HTTPS + 도메인 설정](#5-https--도메인-설정)
6. [SSE 설정 전략](#6-sse-설정-전략)
7. [스케일링 아키텍처](#7-스케일링-아키텍처)
8. [RAG 품질 개선](#8-rag-품질-개선)
9. [Harness Engineering 강화](#9-harness-engineering-강화)
10. [엔터프라이즈 로드맵](#10-엔터프라이즈-로드맵)

---

## 1. 현재 상태 체크

### ✅ 완료된 것들

| 영역 | 항목 | 비고 |
|------|------|------|
| **코어** | FastAPI + FastMCP Streamable HTTP | MCP 1.26.0, stateless_http=True |
| **DB** | PostgreSQL + pgvector, 전체 ORM | specs, chunks, rules, skills, code nodes |
| **RAG** | 청킹 + 하이브리드 검색(벡터+FTS+RRF) | 1800자/180 오버랩, k=60 RRF |
| **임베딩** | Local(sentence-transformers)/OpenAI/Bedrock 멀티백엔드 | 추상 인터페이스로 교체 가능 |
| **비동기** | Celery + Redis 작업 큐 + 모니터링 UI | 실패 기록, 90일 TTL |
| **규칙/스킬** | Global/Repo/App 3계층 + 섹션 분리 + 버전 관리 | append-only, rollback 가능 |
| **Admin UI** | 기획서/규칙/스킬/Celery 모니터링 | 5개 모듈로 분리 완료 |
| **보안** | CSRF(Redis), Host 게이트, CORS 화이트리스트, JWT | MCP_BYPASS 플래그로 개발 우회 가능 |
| **코드 분석** | Python/JS AST 파서, 코드 그래프(노드+엣지) | 영향도 분석 BFS 탐색 |
| **인프라** | Docker Compose + Kubernetes YAML | HPA, Admin/Web/Worker 분리 |
| **에이전트팀** | 7개 역할 정의, tmux 대시보드 | pm/planner/senior/coder/tester/infra/archivist |
| **CI** | GitHub Actions (PG+Redis 서비스 포함) | 테스트 커버리지 목표 50% |

### ⚠️ 미완성 / 취약한 것들

| 영역 | 문제 | 심각도 |
|------|------|--------|
| 테스트 커버리지 | 현재 ~10% (목표 50%) | HIGH |
| 모니터링 | Grafana/Datadog 미구성 | HIGH |
| RAG 품질 | 기획서 매칭 정확도 부족, 에이전트 tool 오사용 | HIGH |
| 문서 임베딩 | Celery 큐 밀릴 때 청킹 지연 | MEDIUM |
| 청킹 전략 | 마크다운 구조 미활용, 한국어 최적화 부족 | MEDIUM |
| Stage 환경 | 실제 AWS 리소스 미프로비저닝 | HIGH |
| HTTPS/도메인 | dev까지만 HTTP, stage 이후 미설정 | HIGH |

### 📊 품질 점수 (현재)

```
보안:        ████████░░  8/10  (Phase 1 완료)
테스트:      ██░░░░░░░░  2/10  (Phase 3 진행 필요)
인프라:      ████░░░░░░  4/10  (stage/prod 미프로비저닝)
RAG 품질:    ████░░░░░░  4/10  (청킹/검색 개선 필요)
모니터링:    ██░░░░░░░░  2/10  (메트릭 수집만 됨)
에이전트팀:  ████████░░  8/10  (7역할 완성)
```

---

## 2. 수정이 필요한 항목들

### 🔴 즉시 수정 (이번 주)

#### 2-1. RAG 기획서 검색 품질
```
현재 문제:
- 에이전트가 search_spec_and_code / find_historical_reference 중 어느 걸 써야 할지 모름
- 기획서 제목 기반 검색이 내용 기반 검색보다 우선되어야 할 때 구분 못 함
- 청크 단위가 너무 커서 관련도 낮은 내용이 섞임

수정 방향:
- MCP 도구 설명 개선 (어떤 상황에서 어느 도구를 써야 하는지 명시)
- 제목/태그 메타데이터 기반 필터링 추가
- 청크 크기 1800자 → 800자로 축소 (한국어 기획서 특성)
```

#### 2-2. archivist_notes 미작성
```
현재: .claude/archivist_notes/index.md에 항목 없음
문제: 1000줄+ 파일들(admin_rules.py 1821줄, versioned_rules.py 1324줄 등)
      읽기 비용이 매 대화마다 낭비됨
수정: @archivist에게 대용량 파일 분석 메모 작성 요청 (별도 작업)
```

#### 2-3. SSE 게이트 바이패스 설정
```
현재: MCP_BYPASS_TRANSPORT_GATE=true (로컬)
문제: dev EC2에서도 바이패스 상태 → Host 검증 없이 모든 호출 허용
수정: dev EC2에서 MCP_BYPASS=false + dev용 허용 Host 등록
```

### 🟡 단기 수정 (2주 내)

#### 2-4. 테스트 커버리지
- `tests/unit/` 확장: chunking, search_hybrid, versioned_rules
- `tests/integration/` 확장: 업로드→청킹→임베딩→검색 전체 파이프라인

#### 2-5. 모니터링 기반 구성
- Prometheus 메트릭 엔드포인트 (`/metrics`) 활성화
- Docker Compose에 Grafana + Prometheus 서비스 추가 (dev용)

#### 2-6. 청킹 전략 개선
- 한국어 기획서 특성 반영 (단락 구분 강화)
- 섹션 헤더를 청크 컨텍스트에 포함 (현재 메타데이터만)

---

## 3. 배포 환경 전략

### 환경별 개요

```
┌─────────────┬──────────────────────────────────────────────────────────────┐
│ 환경        │ 구성                                                          │
├─────────────┼──────────────────────────────────────────────────────────────┤
│ local (dev) │ Docker Compose, EC2 단일 인스턴스, HTTP, 로컬 임베딩          │
│ stage       │ AWS 실제 리소스 (RDS, ElastiCache), EC2/ECS, HTTP (→ HTTPS)  │
│ prod        │ ECS Fargate 또는 K8s, HTTPS+도메인, CloudFront, 오토스케일링  │
└─────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 3-1. dev 환경 (현재: EC2 단일 인스턴스)

**구성도**
```
EC2 (t3.medium 또는 t3.large)
└── Docker Compose
    ├── web:8001    ← FastAPI + MCP
    ├── worker      ← Celery
    ├── db:5433     ← PostgreSQL + pgvector
    └── redis:6380  ← Redis
```

**현재 .env.local 설정으로 그대로 운영 가능**
- `MCP_BYPASS_TRANSPORT_GATE=true` → SSE/Host 검증 없이 통과
- `CSRF_COOKIE_SECURE=false` → HTTP 쿠키 허용
- `UVICORN_EXTRA_OPTS=--reload` → 핫리로드

**수정 사항 (dev EC2용)**
```bash
# EC2에 올릴 때 .env.dev 별도 관리
MCP_BYPASS_TRANSPORT_GATE=false   # dev도 게이트 켜기
CSRF_COOKIE_SECURE=false           # HTTP니까 false 유지
UVICORN_EXTRA_OPTS=               # EC2는 리로드 불필요
LOG_FORMAT=json                    # CloudWatch 수집용
LOG_LEVEL=INFO
```

---

### 3-2. stage 환경 (신규 프로비저닝 필요)

#### 필요한 AWS 리소스

```
┌─────────────────────────────────────────────────────────────────┐
│ stage 환경 리소스 목록                                           │
├──────────────────────┬──────────────────────────────────────────┤
│ 리소스               │ 스펙 권장                                │
├──────────────────────┼──────────────────────────────────────────┤
│ VPC                  │ 신규 또는 기존 dev VPC 분리              │
│ EC2 또는 ECS         │ t3.large (EC2) / 1vCPU 2GB (ECS Task)   │
│ RDS PostgreSQL       │ db.t3.micro, PostgreSQL 17, pgvector 확장│
│ ElastiCache Redis    │ cache.t3.micro, Redis 7.x               │
│ ECR                  │ Docker 이미지 레지스트리                 │
│ S3                   │ 문서 파일 저장 (선택, 현재는 DB 직접)   │
│ ALB                  │ 로드밸런서 (stage에서는 HTTP, prod는 HTTPS)│
│ Security Group       │ web:8000, db:5432, redis:6379 내부만    │
│ IAM Role             │ ECS Task Role (Bedrock 사용 시 필수)     │
│ CloudWatch           │ 로그 그룹 /ecs/stz-mcp-stage            │
└──────────────────────┴──────────────────────────────────────────┘
```

#### stage docker-compose.stage.yml 예시

```yaml
# infra/docker/docker-compose.stage.yml
services:
  web:
    image: ${ECR_IMAGE}:stage
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${RDS_HOST}:5432/${DB_NAME}
      - CELERY_BROKER_URL=redis://${ELASTICACHE_HOST}:6379/0
      - CELERY_RESULT_BACKEND=redis://${ELASTICACHE_HOST}:6379/0
      - MCPER_HOST_BIND=0.0.0.0
      - MCP_BYPASS_TRANSPORT_GATE=false
      - CSRF_COOKIE_SECURE=false    # stage는 아직 HTTP
      - LOG_FORMAT=json
    ports:
      - "8000:8000"

  worker:
    image: ${ECR_IMAGE}:stage
    command: celery -A app.worker.celery_app.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${RDS_HOST}:5432/${DB_NAME}
      - CELERY_BROKER_URL=redis://${ELASTICACHE_HOST}:6379/0

# db, redis는 RDS/ElastiCache로 교체 → 여기서 제거
```

#### RDS pgvector 설정 (중요!)

```sql
-- RDS 생성 후 반드시 실행
CREATE EXTENSION IF NOT EXISTS vector;
-- embedding 차원은 config의 EMBEDDING_DIM과 반드시 일치
-- 기본: 384 (all-MiniLM-L6-v2)
-- OpenAI text-embedding-3-small: 1536
-- Bedrock Titan v2: 1024
```

#### .env.stage 파일

```bash
# infra/docker/.env.stage (Git에 커밋하지 말 것, AWS Secrets Manager 또는 SSM 권장)
DATABASE_URL=postgresql://stzuser:${RDS_PASSWORD}@stz-stage.xxxx.rds.amazonaws.com:5432/stzdb
CELERY_BROKER_URL=redis://stz-stage.xxxx.cache.amazonaws.com:6379/0
CELERY_RESULT_BACKEND=redis://stz-stage.xxxx.cache.amazonaws.com:6379/0

ADMIN_USER=admin
ADMIN_PASSWORD=<강한 비밀번호, 최소 12자>

EMBEDDING_PROVIDER=local          # stage도 로컬 임베딩 (비용 절약)
EMBEDDING_DIM=384

MCPER_ADMIN_ENABLED=true
MCPER_MCP_ENABLED=true
MCPER_AUTH_ENABLED=false          # stage는 아직 선택

MCP_BYPASS_TRANSPORT_GATE=false
CSRF_COOKIE_SECURE=false          # HTTP

LOG_FORMAT=json
LOG_LEVEL=INFO
```

---

### 3-3. prod 환경 (엔터프라이즈)

```
인터넷
  │
  ▼
Route 53 (도메인: mcp.yourcompany.com)
  │
  ▼
CloudFront (CDN + WAF, HTTPS 종단)
  │ (원본 프로토콜: HTTP)
  ▼
ALB (Application Load Balancer)
  ├── /mcp, /health → ECS Service: web (오토스케일 2~10개)
  └── /admin, /auth → ECS Service: admin (고정 1개)
  │
  ├── ECS Service: worker (Celery, 1~5개)
  │
  ├── RDS Aurora PostgreSQL (Multi-AZ, pgvector)
  └── ElastiCache Redis (클러스터 모드 또는 복제본)
```

---

## 4. 설정 파일 해설

### 설정 파일 우선순위

```
환경변수 (.env.local / .env.stage)
    ↑ 덮어씀
config.{env}.yaml  (예: config.stage.yaml)
    ↑ 덮어씀
config.yaml  (기본값)
    ↑ 기반
config.example.yaml  (참고용 템플릿)
```

### 각 파일의 역할

| 파일 | 역할 | 커밋? |
|------|------|-------|
| `config.example.yaml` | 전체 설정 구조 참고 템플릿 | ✅ |
| `config.local.yaml` | 로컬 개발 YAML 오버라이드 | ✅ (민감정보 없으면) |
| `infra/docker/.env.example` | Docker Compose 환경변수 템플릿 | ✅ |
| `infra/docker/.env.local` | 로컬 Docker 오버라이드 | ✅ (현재 허용) |
| `infra/docker/.env.stage` | Stage AWS 설정 | ❌ (Secrets Manager 사용) |
| `infra/docker/.env.prod` | Prod AWS 설정 | ❌ (Secrets Manager 사용) |

### 핵심 환경변수 해설

```bash
# ─── MCP 보안 ───────────────────────────────────────────────────
MCP_BYPASS_TRANSPORT_GATE=true
# true: Host/Origin 검증 완전 우회 (로컬 개발용)
# false: Host 화이트리스트(mcp_allowed_hosts 테이블) 검사
# prod에서는 반드시 false + 허용 Host 등록

CSRF_COOKIE_SECURE=true
# true: HTTPS에서만 CSRF 쿠키 전송
# false: HTTP도 허용 (dev/stage HTTP 환경)

# ─── 임베딩 ─────────────────────────────────────────────────────
EMBEDDING_PROVIDER=local
# local: sentence-transformers (무료, CPU 필요, 384dim)
# openai: OpenAI API (유료, 1536dim, 품질 높음)
# bedrock: AWS Bedrock Titan v2 (1024dim, AWS 종속)

EMBEDDING_DIM=384
# 이 값은 pgvector 컬럼 차원과 반드시 일치해야 함
# 변경 시 전체 재인덱싱 필요 (알림: EMBEDDING_PROVIDER 변경 시 DIM도 변경)

# ─── Feature Flags ───────────────────────────────────────────────
MCPER_ADMIN_ENABLED=true
# Admin UI 활성화 (K8s에서는 Admin Pod에만 true, Web Pod는 false)

MCPER_MCP_ENABLED=true
# MCP 엔드포인트 활성화

MCPER_AUTH_ENABLED=false
# JWT 인증 미들웨어 활성화 (true 시 AUTH_SECRET_KEY 필수)
```

---

## 5. HTTPS + 도메인 설정

### dev (현재): HTTP만

```
사용자 → http://ec2-ip:8001 → FastAPI
```

### stage: HTTP (ALB 뒤)

```
사용자 → http://stage-alb-dns → ALB → EC2:8000 → FastAPI
설정 변경 없음 (CSRF_COOKIE_SECURE=false 유지)
```

### prod: HTTPS + 도메인 (권장 구성)

#### 방법 1: CloudFront + ALB (권장)

```
mcp.yourcompany.com (Route 53)
    │ HTTPS
    ▼
CloudFront (ACM 인증서, HTTPS 종단)
    │ HTTP (origin protocol: HTTP only)
    ▼
ALB (HTTP:80)
    │
    ▼
ECS/EC2 FastAPI (HTTP:8000)
```

**장점**: FastAPI 앱 코드 변경 없음, WAF 추가 가능, 글로벌 캐시
**설정 변경**:
```bash
CSRF_COOKIE_SECURE=true      # HTTPS 종단이니까 true
ALLOWED_ORIGINS=https://mcp.yourcompany.com
# config.yaml의 security.allowed_origins 추가
```

#### 방법 2: Nginx 리버스 프록시 (EC2 직접 구성)

```nginx
# /etc/nginx/sites-available/stz-mcp
server {
    listen 80;
    server_name mcp.yourcompany.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name mcp.yourcompany.com;

    ssl_certificate /etc/letsencrypt/live/mcp.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.yourcompany.com/privkey.pem;

    # SSE 핵심 설정 (MCP Streamable HTTP)
    location /mcp {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";           # Keep-Alive 유지
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE/스트리밍 필수 설정
        proxy_buffering off;                      # 버퍼링 금지
        proxy_read_timeout 300s;                  # 긴 스트리밍 허용
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

```bash
# Let's Encrypt 인증서 발급
sudo certbot --nginx -d mcp.yourcompany.com
```

#### Cursor/Claude에서 HTTPS MCP 연결 설정

```json
// ~/.cursor/mcp.json 또는 claude_desktop_config.json
{
  "mcpServers": {
    "stz-mcp": {
      "url": "https://mcp.yourcompany.com/mcp",
      "type": "http"
    }
  }
}
```

---

## 6. SSE 설정 전략

### 현재 구성 (Streamable HTTP, stateless)

```python
# app/mcp_app.py
mcp = FastMCP(
    stateless_http=True,    # 각 요청 독립적 (세션 없음)
    json_response=True,     # JSON 응답
    streamable_http_path="/"
)
```

**MCP_BYPASS_TRANSPORT_GATE=true 시 동작:**
- Origin/Host 헤더 검증 완전 우회
- 어떤 클라이언트에서도 /mcp 호출 가능
- dev/stage 초기에 적합

**MCP_BYPASS_TRANSPORT_GATE=false 시 동작:**
1. Host 헤더가 `mcp_allowed_hosts` 테이블에 있는지 확인
2. 없으면 421 Misdirected Request 반환
3. 클라이언트 Host는 `app/services/mcp_auto_hosts.py`에서 자동 등록 가능

### 환경별 SSE 설정 권장

```
dev EC2   → MCP_BYPASS=true   (모두 통과)
stage     → MCP_BYPASS=false  + 허용 Host 등록 (테스트용 Cursor IP 등록)
prod      → MCP_BYPASS=false  + Admin UI에서 Host 관리
```

### Nginx에서 SSE 통과시키기 (핵심)

MCP Streamable HTTP는 SSE 스트림을 사용하므로 **반드시** 아래 설정 필요:

```nginx
location /mcp {
    proxy_buffering off;          # ← 이게 없으면 스트림이 버퍼에 쌓여서 실시간 응답 안 됨
    proxy_cache off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_read_timeout 300s;      # ← MCP 응답이 길 수 있음
}
```

ALB 사용 시:
```
ALB 타겟 그룹 → 속성 → "응답 버퍼링" 비활성화
ALB 유휴 타임아웃: 300초로 설정
```

---

## 7. 스케일링 아키텍처

### 현재 (단일 인스턴스)

```
EC2 1대: web + worker + db + redis (Docker Compose)
문제: 단일 장애점, 수직 확장만 가능
```

### Stage 수준 (서비스 분리)

```
EC2 web (t3.large)   ← FastAPI + MCP
EC2 worker (t3.medium) ← Celery
RDS db               ← PostgreSQL + pgvector
ElastiCache          ← Redis
```

### 엔터프라이즈 수준 (K8s 또는 ECS 오토스케일링)

이미 `infra/kubernetes/`에 설정 완료된 구성:

```yaml
# 현재 K8s 구성 요약
Web Deployment:     replicas: 2, HPA max: 10 (CPU 70%)
Worker Deployment:  replicas: 1, HPA max: 5
Admin Deployment:   replicas: 1, Recreate (단일 인스턴스 보장)
```

**핵심 설계 원칙: Web/Admin 분리**

```
Web Pod  → MCPER_ADMIN_ENABLED=false, MCPER_MCP_ENABLED=true
           → 오토스케일 OK (stateless_http=True)

Admin Pod → MCPER_ADMIN_ENABLED=true, MCPER_MCP_ENABLED=false
           → 항상 1개 (CSRF 세션, 파일 업로드 등 상태 있음)
```

**Worker 스케일링 주의사항:**
```
Celery Worker는 임베딩 작업 처리
→ 메모리 집약적 (sentence-transformers ~400MB)
→ Worker replicas 늘릴 때 concurrency 줄이기
→ concurrency=1 * replicas N 방식 권장 (메모리 예측 가능)
```

### ECS Fargate 기준 태스크 스펙 (prod)

```
Web Task:    1 vCPU, 2GB  (stateless, 빠른 스케일)
Worker Task: 2 vCPU, 4GB  (임베딩 모델 상주)
Admin Task:  0.5 vCPU, 1GB (1개 고정)
```

---

## 8. RAG 품질 개선

### 현재 문제 진단

#### 8-1. 에이전트가 도구를 잘못 선택하는 이유

```
현재 MCP 도구 구조:
- upload_document (문서 저장)
- search_documents (검색)           ← 이름이 모호
- find_historical_reference (과거 스펙 검색)  ← 이름이 모호
- push_code_index (코드 인덱싱)
- analyze_code_impact (코드 영향도)

문제:
1. search_documents와 find_historical_reference 차이를 에이전트가 구분 못 함
2. "기획서 찾아줘" → 어느 도구를 써야 하는지 명시 안 됨
3. 도구 설명(description)이 기술적으로만 적혀 있음
```

**해결: 도구 설명 개선 (mcp_tools_docs.py)**

```
search_documents:
  현재: "하이브리드 검색으로 관련 청크 반환"
  개선: "현재 작업과 관련된 기획서나 코드 문서를 찾을 때 사용.
         예: '결제 모듈 관련 기획서', 'auth 관련 코드'
         → 벡터 유사도 + 키워드로 검색"

find_historical_reference:
  현재: "과거 스펙 청크 검색"
  개선: "과거에 비슷한 기능을 어떻게 설계했는지 참고할 때 사용.
         예: '이전에 알림 기능 어떻게 만들었지?', 'OAuth 구현 히스토리'
         → 임베딩 유사도로 의미적으로 유사한 과거 스펙 반환"
```

#### 8-2. 청킹 전략 개선

**현재 설정:**
```python
chunk_size = 1800  # 문자
chunk_overlap = 180
separators = ["\n\n", "\n", ". ", " ", ""]
```

**문제:**
- 한국어 기획서는 1800자가 너무 큼 (맥락이 흐려짐)
- 마크다운 헤더가 청크 경계에서 잘려나감
- 섹션(배경/목적/기능명세/API)이 하나의 청크에 섞임

**개선 방향:**

```python
# 기획서 타입별 청킹 전략
class SpecChunkStrategy:
    HEADING_AWARE = "heading_aware"   # H1/H2 경계로 분할 (기획서)
    PARAGRAPH = "paragraph"           # 단락 기반 (일반 문서)
    CODE = "code"                     # 코드 블록 보존

# 권장 설정 (한국어 기획서)
chunk_size = 800        # 1800 → 800 (한국어 ~200-250 어절)
chunk_overlap = 100     # 180 → 100
# 헤더 경계 우선 분할: ## 배경, ## 목적, ## 기능 각각 별도 청크
```

**헤더 기반 청킹 예시:**
```
[기획서 원문]
# 결제 모듈 기획서
## 배경
현재 결제 시스템은 PG사 직접 연동...

## 기능 명세
1. 카드 결제
2. 간편결제

→ 청크 1: "# 결제 모듈 기획서\n## 배경\n현재 결제..."
→ 청크 2: "# 결제 모듈 기획서\n## 기능 명세\n1. 카드..."
          (헤더를 매 청크에 포함 → 컨텍스트 유지)
```

#### 8-3. 연관 기획서 검색 개선

**현재:** 순수 하이브리드 검색 (벡터+FTS RRF)

**추가 개선 포인트:**

```
1. 메타데이터 필터링
   - app_target 필터: "같은 앱의 기획서만"
   - 날짜 필터: "최근 6개월 기획서만"
   - search_documents에 filter_app_target 파라미터 추가

2. 제목 가중치 부여
   - 현재: 제목이 청크에 섞여서 가중치 없음
   - 개선: spec 제목 임베딩을 별도 저장 → 제목 유사도 30% + 내용 유사도 70%

3. 재랭킹 (선택)
   - Cross-encoder 모델로 Top-K 재정렬
   - 비용: 로컬 cross-encoder 모델 추가 (~100MB)
```

#### 8-4. 사용성 진단 방법

**현재 도구 호출 통계는 있음** (`mcp_tool_call_stats`):
```sql
SELECT tool_name, call_count FROM mcp_tool_call_stats ORDER BY call_count DESC;
```

**추가 필요한 측정:**
```
1. 검색 결과 사용률: 반환된 청크를 에이전트가 실제로 사용했는지
2. 검색 실패율: indexed_no_match, no_index 비율
3. 재시도 패턴: 같은 도구를 연속 호출하는 경우
→ 이 데이터로 "에이전트가 어느 시점에서 막히는지" 파악
```

---

## 9. Harness Engineering 강화

### 현재 상태

```
✅ 에이전트 역할 정의 (7개)
✅ 협업 흐름 정의 (pm → planner → senior → coder/tester → infra)
✅ dev_log.md 작업 로그
✅ report_template.md 보고 형식
✅ archivist_notes 인덱스 (아직 내용 없음)
✅ @archivist 1000줄+ 파일 전담

⚠️ Skills/Rules: 충분한가? → 보완 필요
⚠️ MCP 도구 설명 퀄리티 낮음 → 에이전트 오사용 원인
⚠️ archivist_notes 비어있음 → 대용량 파일 매번 재읽기
```

### Skills & Rules 충분성 판단

**현재 구조:**
```
Global Rule: 모든 에이전트에 적용되는 규칙
Repo Rule: 특정 저장소에만 적용
App Rule: 특정 앱에만 적용

Global Skill: 공통 배경 지식
App Skill: 앱별 배경 지식
```

**현재 문제: 에이전트가 규칙/스킬을 올바르게 활용하지 못하는 경우**

```
문제 1: get_global_rule 호출 타이밍
→ 에이전트가 작업 시작 시 규칙을 먼저 조회해야 하는데
  도구 설명에 "초기화 순서"가 명시되어 있긴 하나 (mcp_app.py instructions)
  에이전트가 이를 무시하고 바로 작업 시작하는 경우

→ 개선: mcp_app.py instructions를 더 강하게 작성
  "반드시 첫 번째 도구 호출로 get_global_rule을 실행하라"

문제 2: 섹션 미인식
→ 규칙이 섹션 분리되었지만 에이전트가 어느 섹션을 봐야 하는지 모름

→ 개선: 섹션 목적 문서화 + list_rule_sections 호출 권장
```

### 하네스 엔지니어링 개선 로드맵

#### 추가하면 도움될 것들

```
1. Prompt 품질 관리
   현재: app/prompts/ko/, en/ 분리 완료
   추가: 각 도구별 "언제 쓰면 안 되는지" 역예시 추가
         (negative examples가 없으면 에이전트 오사용 방지 어려움)

2. Tool 호출 검증 (자동)
   현재: 도구 호출 통계만 기록
   추가: 도구 파라미터 유효성 + 응답 품질 자동 점수화
         예: search_documents 결과가 0개면 "검색 미스" 로깅

3. 에이전트 피드백 루프
   현재: 없음
   추가: 에이전트가 "이 검색 결과가 유용했나요?" 체크
         → mcp_tool_call_stats에 useful/not_useful 기록

4. Rule/Skill 버전 알림
   현재: check_rule_versions로 버전 확인 가능
   추가: 에이전트가 시작 시 자동으로 버전 변경 감지
         → 새 규칙 발행 시 다음 호출에서 자동으로 최신 버전 로드

5. @archivist 노트 채우기 (즉시 가능)
   분석 대상:
   - app/services/versioned_rules.py (1324줄)
   - app/routers/admin_rules.py (1821줄)
   - app/routers/admin.py (1471줄)
   - app/routers/admin_skills.py (1077줄)
   → 각 파일 분석 메모를 .claude/archivist_notes/에 저장
   → 이후 대화에서 파일 재읽기 없이 메모 재활용
```

---

## 10. 엔터프라이즈 로드맵

### 단계별 목표

```
Phase 3 (현재 → 4월):  테스트 강화 + RAG 품질 개선
Phase 4 (4-5월):       Stage 배포 + 모니터링
Phase 5 (5-6월):       Prod 배포 + HTTPS + 도메인
Phase 6 (6월+):        엔터프라이즈 기능 (RBAC, 감사 로그, 멀티테넌시)
```

### Phase 3: 테스트 + RAG (즉시)

```
□ 청킹 크기 1800 → 800 조정
□ 도구 설명 개선 (언제/왜 쓰는지 명확화)
□ archivist_notes 대용량 파일 분석 메모 작성
□ 단위 테스트 40개+ (chunking, search, rules)
□ 통합 테스트 20개+ (업로드→임베딩→검색 파이프라인)
□ 검색 실패율 로깅 추가
```

### Phase 4: Stage 배포 + 모니터링

```
□ AWS 리소스 프로비저닝 (RDS, ElastiCache, ECR, ALB)
□ .env.stage 설정 + AWS Secrets Manager 연동
□ Prometheus + Grafana 대시보드 구성
  - /metrics 엔드포인트 활성화
  - Celery 작업 큐 깊이 모니터링
  - 검색 응답시간 P50/P95/P99
□ CloudWatch 로그 그룹 설정
□ 알림 설정 (작업 실패, DB 연결 실패)
```

### Phase 5: Prod HTTPS + 도메인

```
□ Route 53 도메인 등록
□ ACM 인증서 발급 (*.yourcompany.com)
□ CloudFront 배포 생성 (HTTPS 종단)
□ ALB 연결 (HTTP origin)
□ Nginx 설정 업데이트 (proxy_buffering off, SSE 타임아웃)
□ CSRF_COOKIE_SECURE=true, ALLOWED_ORIGINS 업데이트
□ MCP 클라이언트 URL 업데이트 (http → https)
```

### Phase 6: 엔터프라이즈

```
□ RBAC: Admin/Viewer/Editor 권한 분리
□ 감사 로그: 누가 언제 어떤 규칙/기획서를 변경했는지
□ 멀티테넌시: 팀별 규칙/기획서 분리
□ OpenAI/Bedrock 임베딩 전환 (품질 향상)
□ 임베딩 캐시 (Redis): 동일 텍스트 재임베딩 방지
□ 배치 재인덱싱 스케줄러 (임베딩 모델 교체 시)
□ MCP 도구 사용 분석 대시보드
□ Slack/Teams 알림 연동 (규칙 변경 시 팀 알림)
```

---

## 요약 체크리스트

### 지금 당장 해야 할 것

- [ ] `archivist_notes` 채우기 (대용량 파일 4개)
- [ ] MCP 도구 설명 개선 (`mcp_tools_docs.py`)
- [ ] 청킹 크기 조정 (1800 → 800)
- [ ] dev EC2 `.env.dev` 파일 생성 (MCP_BYPASS=false)
- [ ] `mcp_app.py` instructions 강화 (규칙 먼저 조회 명시)

### Stage 배포 전 필수

- [ ] AWS 리소스 프로비저닝 목록 확인 (섹션 3-2)
- [ ] RDS pgvector 확장 설치
- [ ] `.env.stage` + AWS Secrets Manager 설정
- [ ] Nginx SSE 설정 (`proxy_buffering off`)

### Prod 이전 필수

- [ ] HTTPS 인증서 (ACM 또는 Let's Encrypt)
- [ ] `CSRF_COOKIE_SECURE=true`
- [ ] `MCP_BYPASS_TRANSPORT_GATE=false` + Host 화이트리스트
- [ ] 모니터링 알림 설정
- [ ] 테스트 커버리지 50%+ 달성

---

*이 문서는 2026-03-31 기준 프로젝트 상태를 반영합니다.*
*다음 리뷰: Phase 3 완료 후 (예상 2026-04-14)*
