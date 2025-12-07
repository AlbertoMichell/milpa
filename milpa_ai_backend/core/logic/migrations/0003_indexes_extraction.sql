-- milpa_ai_backend/core/logic/migrations/0003_indexes_extraction.sql
-- Índices para consultar fragments/tablas con buen rendimiento.

CREATE INDEX IF NOT EXISTS idx_frag_doc ON fragments(doc_id);
CREATE INDEX IF NOT EXISTS idx_frag_page ON fragments(page_start, page_end);
CREATE INDEX IF NOT EXISTS idx_tables_doc ON tables(doc_id);
