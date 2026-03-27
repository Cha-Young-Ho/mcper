# 로컬 임베딩 폴백 (서버 MCP·워커 부하 시)

서버가 바쁠 때( Celery 큐 깊이 증가, GPU/CPU 임베딩 병목 ) 기획서 벡터화를 **클라이언트 쪽**에서 끝내고 DB만 갱신하는 흐름이다.

## 언제 쓰나

- `GET /health/rag` 에서 `celery_queue_depth` 가 계속 크다.
- `upload_spec_to_db` 직후 `chunk_index_queued` 는 true 인데 인덱스가 한참 뒤에야 생긴다.
- 서버 워커를 늘리기 어렵고, 개발자 PC·로컬 LLM으로 임베딩하는 비용이 더 싸다.

## 절차 (MCP 툴)

1. **`upload_spec_to_db`** 로 `specs` 행을 만든다. 응답의 `id` = `spec_id`.
2. 로컬에서 기획서 본문을 서버와 **동일한** 청킹·모델 규칙으로 자른 뒤 임베딩한다.  
   - 차원은 서버 `EMBEDDING_DIM` 과 **반드시 일치** (기본 MiniLM → 384).
3. **`push_spec_chunks_with_embeddings(spec_id, chunks_json)`** 호출.  
   - `chunks_json` 예: `[{"content":"…","embedding":[…], "metadata":{…}}]`  
   - 기존 해당 `spec_id` 의 `spec_chunks` 는 **전부 삭제 후 교체**된다.

## 절차 (DB 직접 — 스크립트)

같은 네트워크에서 Postgres 에 붙을 수 있으면:

```bash
export DATABASE_URL=postgresql://...
python scripts/local_embed_spec.py <spec_id>
```

내부적으로는 `index_spec_synchronously` (서버 워커와 동일한 청킹·`embed_texts`) 를 실행한다.

## 운영 주의

- **모델 불일치**면 검색 품질이 망가진다. 스테이징·프로덕션의 `LOCAL_EMBEDDING_MODEL` / `EMBEDDING_DIM` 을 문서화할 것.
- 로컬 폴백은 **코드 원본을 서버로 보내지 않는다**. 기획서 텍스트·벡터만 다룬다.
