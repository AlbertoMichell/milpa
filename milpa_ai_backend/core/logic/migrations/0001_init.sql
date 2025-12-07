-- milpa_ai_backend/core/logic/migrations/0001_init.sql
-- Esquema inicial mínimo + tablas extendidas para licencias y referencias finas.
-- Ejecutado por yoyo-migrations.

-- Metadatos de documentos
CREATE TABLE IF NOT EXISTS docs (
  doc_id TEXT PRIMARY KEY,          -- SHA-256 del archivo (identificador estable)
  title TEXT,
  author TEXT,
  year INT,
  source TEXT,                      -- nombre del archivo/subida
  hash TEXT,                        -- redundante=doc_id (útil para búsquedas por hash)
  license TEXT,                     -- institutional | public_domain | permitted | normative
  lang_original TEXT,               -- detectado en extracción
  classification TEXT,              -- Publico | Interno | Restringido
  created_at TEXT
);

-- Fragmentos (se llenará en SPRINTs siguientes)
CREATE TABLE IF NOT EXISTS fragments (
  fragment_id TEXT PRIMARY KEY,
  doc_id TEXT,
  fragment_uid TEXT,
  section_id TEXT,
  page_start INT,
  page_end INT,
  text TEXT,
  text_es TEXT,
  source TEXT,                      -- "native" | "ocr"
  created_at TEXT
);

-- Referencias finas (coordenadas para clic-through en UI)
CREATE TABLE IF NOT EXISTS fine_refs (
  fragment_id TEXT,
  page INT,
  x1 REAL, y1 REAL, x2 REAL, y2 REAL,  -- bbox PDF coords
  click_href TEXT,                     -- ruta interna UI para viewer
  PRIMARY KEY (fragment_id, page, x1, y1, x2, y2)
);

-- Tablas detectadas (estructura y CSV crudo por página)
CREATE TABLE IF NOT EXISTS tables (
  table_id TEXT PRIMARY KEY,
  doc_id TEXT,
  page INT,
  bbox TEXT,         -- JSON [x1,y1,x2,y2]
  csv TEXT,          -- representación csv de la tabla
  schema JSON
);

-- Celdas de tabla (para cita por celda)
CREATE TABLE IF NOT EXISTS table_cells (
  table_id TEXT,
  row INT,
  col INT,
  text TEXT,
  bbox TEXT,
  PRIMARY KEY (table_id, row, col)
);

-- Figuras
CREATE TABLE IF NOT EXISTS figures (
  figure_id TEXT PRIMARY KEY,
  doc_id TEXT,
  page INT,
  bbox TEXT,
  caption TEXT
);

-- Licencias (detalle)
CREATE TABLE IF NOT EXISTS licenses (
  doc_id TEXT PRIMARY KEY,
  license TEXT,
  url TEXT,
  checked_by TEXT,
  checked_at TEXT
);

-- Índices útiles
CREATE INDEX IF NOT EXISTS idx_docs_created ON docs(created_at);
CREATE INDEX IF NOT EXISTS idx_tables_doc ON tables(doc_id);
CREATE INDEX IF NOT EXISTS idx_fine_refs_frag ON fine_refs(fragment_id);
