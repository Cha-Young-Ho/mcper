# docs/generated/db-schema.md — 데이터베이스 스키마

**생성 일자**: 2026-03-30

**주의**: 이 파일은 자동 생성됩니다. 수동 편집하지 마세요.

---

## 테이블 목록

### 1. specs — 기획서

```sql
CREATE TABLE specs (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    app_target VARCHAR(100) NOT NULL,
    base_branch VARCHAR(100) DEFAULT 'main',
    related_files JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (app_target),
    INDEX (created_at DESC)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | 기획서 ID (PK) |
| title | VARCHAR(255) | 제목 (유니크) |
| content | TEXT | 본문 |
| app_target | VARCHAR(100) | 대상 앱 |
| base_branch | VARCHAR(100) | 기준 브랜치 (기본값: main) |
| related_files | JSONB | 관련 파일 JSON 배열 |
| created_at | TIMESTAMP | 생성 시각 |
| updated_at | TIMESTAMP | 수정 시각 |

---

### 2. spec_chunks — 기획서 청크 (벡터)

```sql
CREATE TABLE spec_chunks (
    id SERIAL PRIMARY KEY,
    spec_id INT NOT NULL REFERENCES specs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (spec_id),
    INDEX USING ivfflat (embedding vector_cosine_ops)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | 청크 ID (PK) |
| spec_id | INT | 기획서 ID (FK) |
| content | TEXT | 청크 텍스트 |
| embedding | vector(384) | 벡터 임베딩 (기본 차원: 384) |
| created_at | TIMESTAMP | 생성 시각 |

**인덱스**:
- `IVFFLAT`: 벡터 유사도 검색 (코사인 거리)

---

### 3. code_nodes — 코드 노드

```sql
CREATE TABLE code_nodes (
    id SERIAL PRIMARY KEY,
    app_target VARCHAR(100) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    node_type VARCHAR(50),  -- 'function', 'class', 'module'
    node_name VARCHAR(255) NOT NULL,
    content TEXT,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (app_target, file_path),
    UNIQUE (app_target, file_path, node_name)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | 노드 ID (PK) |
| app_target | VARCHAR(100) | 앱 이름 |
| file_path | VARCHAR(255) | 파일 경로 |
| node_type | VARCHAR(50) | 노드 타입 (function, class, module) |
| node_name | VARCHAR(255) | 함수/클래스명 |
| content | TEXT | 코드 스니펫 |
| embedding | vector(384) | 벡터 임베딩 |
| created_at | TIMESTAMP | 생성 시각 |

---

### 4. code_edges — 코드 의존성

```sql
CREATE TABLE code_edges (
    id SERIAL PRIMARY KEY,
    from_node_id INT NOT NULL REFERENCES code_nodes(id) ON DELETE CASCADE,
    to_node_id INT NOT NULL REFERENCES code_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(50),  -- 'calls', 'imports', 'extends'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (from_node_id),
    INDEX (to_node_id),
    UNIQUE (from_node_id, to_node_id, edge_type)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | 엣지 ID (PK) |
| from_node_id | INT | 출발 노드 (FK) |
| to_node_id | INT | 도착 노드 (FK) |
| edge_type | VARCHAR(50) | 관계 타입 (calls, imports, extends) |
| created_at | TIMESTAMP | 생성 시각 |

---

### 5. global_rule_versions — 전역 규칙

```sql
CREATE TABLE global_rule_versions (
    version INT PRIMARY KEY,
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (created_at DESC)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| version | INT | 버전 (PK, 자동 증가) |
| body | TEXT | 규칙 본문 (Markdown) |
| created_at | TIMESTAMP | 발행 시각 |

**특징**: Append-only (INSERT만, UPDATE/DELETE 금지)

---

### 6. repo_rule_versions — 저장소 규칙

```sql
CREATE TABLE repo_rule_versions (
    pattern VARCHAR(255) NOT NULL,  -- URL 패턴
    version INT NOT NULL,
    sort_order INT DEFAULT 0,
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (pattern, version),
    INDEX (created_at DESC)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| pattern | VARCHAR(255) | URL 패턴 (PK 1부) |
| version | INT | 버전 (PK 2부, 패턴별 자동 증가) |
| sort_order | INT | 정렬 순서 |
| body | TEXT | 규칙 본문 |
| created_at | TIMESTAMP | 발행 시각 |

**예**: pattern = \"github.com/your-org/*\"

---

### 7. app_rule_versions — 앱 규칙

```sql
CREATE TABLE app_rule_versions (
    app_name VARCHAR(100) NOT NULL,
    version INT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (app_name, version),
    INDEX (created_at DESC)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| app_name | VARCHAR(100) | 앱 이름 (PK 1부) |
| version | INT | 버전 (PK 2부, 앱별 자동 증가) |
| body | TEXT | 규칙 본문 |
| created_at | TIMESTAMP | 발행 시각 |

---

### 8. mcp_allowed_hosts — MCP 허용 Host

```sql
CREATE TABLE mcp_allowed_hosts (
    id SERIAL PRIMARY KEY,
    host VARCHAR(255) NOT NULL UNIQUE,  -- \"host:port\"
    added_by VARCHAR(100),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | ID (PK) |
| host | VARCHAR(255) | Host 헤더 값 (유니크) |
| added_by | VARCHAR(100) | 추가자 |
| added_at | TIMESTAMP | 추가 시각 |

**예**: host = \"mcp.example.com:443\"

---

### 9. mcp_tool_call_stats — MCP 도구 호출 통계

```sql
CREATE TABLE mcp_tool_call_stats (
    tool_name VARCHAR(100) PRIMARY KEY,
    call_count INT DEFAULT 0,
    last_called_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| tool_name | VARCHAR(100) | 도구명 (PK) |
| call_count | INT | 누적 호출 수 |
| last_called_at | TIMESTAMP | 마지막 호출 시각 |
| updated_at | TIMESTAMP | 업데이트 시각 |

---

### 10. auth_users — 사용자 계정

```sql
CREATE TABLE auth_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN DEFAULT false,
    is_forced_password_change BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | SERIAL | 사용자 ID (PK) |
| username | VARCHAR(100) | 사용자명 (유니크) |
| email | VARCHAR(255) | 이메일 |
| password_hash | VARCHAR(255) | 비밀번호 해시 (bcrypt) |
| is_admin | BOOLEAN | 어드민 여부 |
| is_forced_password_change | BOOLEAN | 강제 변경 필요 여부 |
| created_at | TIMESTAMP | 생성 시각 |
| updated_at | TIMESTAMP | 수정 시각 |

---

### 11. celery_tasks — Celery 작업 로그

```sql
CREATE TABLE celery_tasks (
    id VARCHAR(100) PRIMARY KEY,
    task_name VARCHAR(255) NOT NULL,
    status VARCHAR(50),  -- 'pending', 'started', 'success', 'failure'
    result JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (task_name),
    INDEX (status),
    INDEX (created_at DESC)
);
```

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| id | VARCHAR(100) | Celery 태스크 ID (PK) |
| task_name | VARCHAR(255) | 태스크명 |
| status | VARCHAR(50) | 상태 |
| result | JSONB | 결과 데이터 |
| error_message | TEXT | 에러 메시지 |
| started_at | TIMESTAMP | 시작 시각 |
| completed_at | TIMESTAMP | 완료 시각 |
| created_at | TIMESTAMP | 생성 시각 |

---

## 인덱스 전략

### 성능 최적화

| 테이블 | 인덱스 | 용도 |
|--------|--------|------|
| specs | (app_target, created_at) | 앱별·시간순 조회 |
| spec_chunks | IVFFLAT (embedding) | 벡터 유사도 검색 |
| code_nodes | (app_target, file_path) | 앱·파일별 조회 |
| code_edges | (from_node_id), (to_node_id) | 의존성 그래프 순회 |
| mcp_tool_call_stats | (tool_name) | 도구 통계 조회 |

---

## 마이그레이션 이력

### v1.0 (2026-03-01)
- 초기 스키마

### v1.1 (2026-03-15)
- `specs.title` 컬럼 추가
- FTS 인덱스 추가

### v1.2 (2026-03-30)
- `celery_tasks` 테이블 추가
- `code_nodes`, `code_edges` 추가 (준비)

---

## 관련 문서

- **ARCHITECTURE.md** — 데이터 모델 개요
- **docs/DESIGN_SUMMARY.md** — 기술 설계 요약
"