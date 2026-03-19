-- 기존 DB에 specs.title 이 없을 때 한 번 실행 (Postgres)
ALTER TABLE specs ADD COLUMN IF NOT EXISTS title VARCHAR(512);
