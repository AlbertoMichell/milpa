-- Posición del fragmento en la página (PDF coords). Permite citar con
-- precisión visual (x1,y1,x2,y2) sin recurrir a fine_refs por línea.

ALTER TABLE fragments ADD COLUMN bbox TEXT;  -- JSON [x1,y1,x2,y2] o NULL
ALTER TABLE fragments ADD COLUMN char_count INTEGER;
CREATE INDEX IF NOT EXISTS idx_fragments_doc_page_seq2
  ON fragments(doc_id, page_start, seq);
