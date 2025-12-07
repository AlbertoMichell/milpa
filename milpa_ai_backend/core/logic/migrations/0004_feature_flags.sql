-- milpa_ai_backend/core/logic/migrations/0004_feature_flags.sql
-- Tabla de feature flags dinámicos (SPRINT 20)

CREATE TABLE IF NOT EXISTS feature_flags (
    flag_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    config_json TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Feature flags por defecto
INSERT OR IGNORE INTO feature_flags (flag_name, enabled, config_json, description)
VALUES 
    ('RERANKER_ENABLED', 0, '{"model": "cross-encoder/ms-marco-MiniLM-L6-v2"}', 'Habilitar reranker para mejorar relevancia'),
    ('EMBEDDINGS_MODEL', 1, '{"model": "paraphrase-multilingual-MiniLM-L12-v2", "dimensions": 384}', 'Modelo de embeddings multilingüe'),
    ('RAG_MODE', 1, '{"mode": "hybrid", "bm25_weight": 0.4, "vector_weight": 0.6}', 'Configuración de modo RAG'),
    ('OCR_ENABLED', 1, '{"tesseract_lang": "spa+eng", "min_text_threshold": 50}', 'OCR para documentos escaneados'),
    ('BLUE_GREEN_V2_ENABLED', 0, '{"rollout_percent": 0}', 'Deploy blue-green UI v2'),
    ('TABLE_EXTRACTION_MODE', 1, '{"mode": "auto", "lattice": true, "stream": true}', 'Extracción de tablas con Camelot'),
    ('ENRICHMENT_ENABLED', 1, '{"extract_entities": true, "classify_labels": true}', 'Enriquecimiento con taxonomía'),
    ('AV_STRICT_MODE', 1, '{"scan_uploads": true, "scan_instream": true}', 'Antivirus estricto en uploads');
