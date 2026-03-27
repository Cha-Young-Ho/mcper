# Master Context — 엔터프라이즈 기획서–코드 매칭 분산 RAG

온보딩 개발자·로컬 AI 에이전트(Cursor 등)에게 **설계 의도와 제약**을 한 번에 주입하기 위한 문서다. 상세 폴백 절차는 [`LOCAL_EMBEDDING_FALLBACK.md`](LOCAL_EMBEDDING_FALLBACK.md), MCP Host 자동 등록은 [`../app/services/mcp_auto_hosts.py`](../app/services/mcp_auto_hosts.py) 를 본다.

---

## Part 1: 아키텍처 결정 히스토리 (Q&A)

**Q: 데이터를 벡터화하는 데 필요한 게 뭐야?**  
A: 전처리, 임베딩 모델, 연산 자원, 벡터를 넣을 저장소(pgvector 등).

**Q: 여러 명이 한 서버에 기획서를 올릴 때 최적화 팁?**  
A: 동기 처리로 버티기 어렵다. 업로드는 즉시 응답하고, Redis + Celery 워커로 비동기 임베딩. 텍스트는 overlap 청킹, 배치로 임베딩.

**Q: 청킹을 로컬 에이전트가 하면?**  
A: 가능하다. 다만 기획서와 코드의 의미 간극이 크므로, 코드 업로드 시 **자연어 요약**을 같이 올리고 **Feature ID 등 메타데이터**로 기획과 묶어라.

**Q: 벡터 DB와 CRUD를 같이 쓰려면?**  
A: PostgreSQL + `pgvector` 로 한 트랜잭션에서 권한·메타·유사도 검색을 묶는 편이 동기화 이슈가 적다.

**Q: EC2에서 MCP SSE/Streamable HTTP 가 421?**  
A: MCP SDK의 DNS 리바인딩 보호. ALB + Nginx + HTTPS, `MCP_ALLOWED_HOSTS`(또는 이 레포의 **기동 시 DB 동기화**)로 화이트리스트를 명시한다.

**Q: 엑셀·PDF·PPT 등 다양한 입력?**  
A: 파서로 **표준 텍스트 + 메타데이터**로 통일하고, 배치·실시간 모두 같은 전처리 모듈을 쓴다.

**Q: 코드가 너무 크면?**  
A: 파일 단위로 **요약본만 벡터화**하고, 검색 시 **경로 목록만** 주고 로컬 에이전트가 필요한 파일만 읽게 한다.

**Q: 서버에는 코드가 없다?**  
A: 이 레포는 **서버에 소스 코드를 두지 않는** 전제를 지원한다. 서버는 기획서와 **상대 경로**만 매핑하고, 원본은 로컬에서 읽는다.

---

## Part 2: 로컬 AI 에이전트용 시스템 프롬프트 (복사용)

아래 블록을 `.cursorrules` 또는 에이전트 시스템 프롬프트에 넣을 수 있다.

```markdown
# [Role]
당신은 엔터프라이즈 기획서-코드 매칭 RAG 시스템을 구동하는 수석 로컬 AI 에이전트이다.
목표는 유저가 제공하는 '기획서(자연어)'와 로컬 환경의 '소스 코드'를 연결해 맥락에 맞는 코드를 생성·수정·해설하는 것이다.

# [CRITICAL CONSTRAINTS]
1. **No Code on Server:** 중앙 MCP 서버에는 소스 코드가 없다. 서버는 기획서 텍스트와 **상대 경로**만 가진다.
2. **Local File Access:** 서버가 준 경로로 로컬(IDE) 파일을 읽는다.
3. **Never Upload Code:** 로컬 코드 전문을 MCP 서버로 보내지 않는다. 경로·기획서 자연어 중심 통신.

# [Workflow: 2-Stage Retrieval]
### Step 1: 의미 검색 및 경로 확보 (MCP)
요청을 MCP로 보내 유사 기획과 `related_file_paths` 를 받는다.

### Step 2: 로컬 코드 열람
반환된 경로 중 필요한 2~3개만 읽고, 의존성이 있으면 추가로 연다.

### Step 3: 종합
과거 기획 맥락 + 로컬 실제 코드 + 새 요청을 합쳐 답한다.

# [Additional Rules]
- 경로 기반 역검색: "이 파일의 기획 찾기"는 경로 메타 필터로 요청한다.
- 서버 경로는 **프로젝트 루트 기준 상대 경로**이다.
```

---

## 이 레포와의 연결

| 주제 | 구현 위치 |
|------|-----------|
| MCP Host 자동 등록 | `app/services/mcp_auto_hosts.py`, `main.py` lifespan |
| Host 게이트 | `app/asgi/mcp_host_gate.py` |
| 스펙 임베딩(워커) | `app/worker/tasks.py` |
| 로컬 벡터 삽입 MCP 툴 | `push_spec_chunks_with_embeddings` in `app/tools/rag_tools.py` |
| 큐·브로커 헬스 | `GET /health/rag` |
