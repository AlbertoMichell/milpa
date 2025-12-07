-- milpa_ai_backend/core/logic/migrations/0002_add_stored_path.sql
-- Agrega stored_path a docs para localizar el archivo original por doc_id.

ALTER TABLE docs ADD COLUMN stored_path TEXT;

-- Índices útiles
CREATE INDEX IF NOT EXISTS idx_docs_source ON docs(source);
CREATE INDEX IF NOT EXISTS idx_docs_hash   ON docs(hash);
