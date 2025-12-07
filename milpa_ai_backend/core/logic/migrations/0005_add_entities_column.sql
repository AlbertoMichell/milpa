-- milpa_ai_backend/core/logic/migrations/0005_add_entities_column.sql
-- Agregar columna 'entities' a la tabla fragments para almacenar entidades extraídas

-- Agregar columna entities (JSON serializado)
ALTER TABLE fragments ADD COLUMN entities TEXT;

-- Índice para búsquedas por entidades (opcional pero recomendado)
CREATE INDEX IF NOT EXISTS idx_fragments_entities ON fragments(entities);
