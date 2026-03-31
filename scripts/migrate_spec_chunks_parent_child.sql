-- spec_chunks Parent-Child 구조 마이그레이션
-- 실행: psql $DATABASE_URL -f scripts/migrate_spec_chunks_parent_child.sql
-- 멱등성: 컬럼이 이미 있으면 오류 없이 건너뜀

BEGIN;

-- 1. embedding nullable 허용 (parent 는 embedding 없음)
ALTER TABLE spec_chunks
    ALTER COLUMN embedding DROP NOT NULL;

-- 2. chunk_type 컬럼 추가 (기존 행 = 'child')
ALTER TABLE spec_chunks
    ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(16) NOT NULL DEFAULT 'child';

-- 3. parent_chunk_id FK 추가 (자기 참조)
ALTER TABLE spec_chunks
    ADD COLUMN IF NOT EXISTS parent_chunk_id INTEGER
        REFERENCES spec_chunks(id) ON DELETE SET NULL;

-- 4. 검색 필터 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_spec_chunks_chunk_type
    ON spec_chunks(chunk_type);

CREATE INDEX IF NOT EXISTS idx_spec_chunks_parent_chunk_id
    ON spec_chunks(parent_chunk_id)
    WHERE parent_chunk_id IS NOT NULL;

COMMIT;
