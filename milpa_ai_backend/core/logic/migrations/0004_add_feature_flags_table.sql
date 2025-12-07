-- Migration: 0004_add_feature_flags_table.sql
-- Tabla para feature flags dinámicos (reemplazo de variables de entorno estáticas)
-- yoyo apply: Crea tabla feature_flags
-- yoyo rollback: Elimina tabla feature_flags

-- depends: 0003_indexes_extraction

-- ────────────────────────────────────────────────────────────────
-- UP: Crear tabla de feature flags
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS feature_flags (
    flag_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,  -- 0=disabled, 1=enabled
    config_json TEXT,                    -- JSON con configuración adicional
    description TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Insertar flags por defecto
INSERT INTO feature_flags (flag_name, enabled, config_json, description) VALUES
    ('RERANKER_ENABLED', 1, '{"model": "cross-encoder/ms-marco-MiniLM-L-6-v2"}', 'Habilita reranker de fragmentos'),
    ('EMBEDDINGS_MODEL', 1, '{"model": "BAAI/bge-m3", "dim": 1024}', 'Modelo de embeddings activo'),
    ('RAG_MODE', 1, '{"mode": "hybrid", "bm25_weight": 0.4, "vector_weight": 0.6}', 'Modo RAG: hybrid, bm25, vector'),
    ('TAXONOMY_VERSION', 1, '{"version": "2025.09.10"}', 'Versión de taxonomía en uso'),
    ('BLUE_GREEN_V2_ENABLED', 0, '{"rollout_percent": 0}', 'Habilita versión v2 de la UI');

-- Crear índice para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_feature_flags_enabled ON feature_flags(enabled);

-- ────────────────────────────────────────────────────────────────
-- DOWN: Rollback - eliminar tabla
-- ────────────────────────────────────────────────────────────────

-- __yoyo_rollback__
DROP TABLE IF EXISTS feature_flags;
DROP INDEX IF EXISTS idx_feature_flags_enabled;
