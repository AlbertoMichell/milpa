-- Orden estable de lectura: fragment_id es UUID; ORDER BY page + seq preserva
-- el orden de extracción (antes el orden en la misma página era arbitrario).

ALTER TABLE fragments ADD COLUMN seq INTEGER;
CREATE INDEX IF NOT EXISTS idx_fragments_doc_page_seq
  ON fragments(doc_id, page_start, seq);
