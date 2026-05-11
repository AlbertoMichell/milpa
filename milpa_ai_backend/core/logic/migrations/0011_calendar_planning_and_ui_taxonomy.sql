-- 0011_calendar_planning_and_ui_taxonomy.sql
-- Catálogos UI dinámicos + reglas de planeación de calendario por cultivo.

-- Catálogo de tipos de evento de calendario (evita hardcoded en UI).
CREATE TABLE IF NOT EXISTS calendar_event_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  color_class TEXT NOT NULL,
  badge_class TEXT NOT NULL,
  border_color TEXT NOT NULL,
  default_priority INTEGER NOT NULL DEFAULT 50,
  action_when_due TEXT NOT NULL,
  basis_notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO calendar_event_types
  (slug, label, color_class, badge_class, border_color, default_priority, action_when_due, basis_notes)
VALUES
  ('sowing', 'Siembra', 'event-sowing', 'bg-primary', '#0d6efd', 10, 'Preparar cama de siembra, verificar humedad y sembrar.', 'Programado según fecha de siembra del cultivo.'),
  ('maintenance', 'Mantenimiento', 'event-maintenance', 'bg-warning text-dark', '#ffc107', 30, 'Ejecutar labores preventivas (deshierbe, revisión de humedad, acolchado).', 'Basado en etapa fenológica y umbrales de manejo.'),
  ('irrigation', 'Riego', 'event-maintenance', 'bg-info text-dark', '#0dcaf0', 25, 'Aplicar riego según déficit de humedad y meta del perfil del cultivo.', 'Fundamentado en humedad del suelo y metas de riego del perfil.'),
  ('fertilization', 'Fertilización', 'event-maintenance', 'bg-success', '#198754', 35, 'Aplicar fertilización recomendada para la etapa del cultivo.', 'Regla agronómica por etapa y contexto del cultivo.'),
  ('monitoring', 'Monitoreo', 'event-maintenance', 'bg-secondary', '#6c757d', 40, 'Registrar lecturas de sensor y validar alertas activas.', 'Frecuencia periódica para salud del cultivo.'),
  ('pest', 'Plagas', 'event-pest', 'bg-danger', '#dc3545', 20, 'Inspeccionar incidencia y aplicar control recomendado.', 'Activado por riesgo climático o historial de plagas.'),
  ('harvest', 'Cosecha', 'event-harvest', 'bg-success', '#198754', 15, 'Verificar madurez fisiológica y planear cosecha.', 'Basado en fecha esperada de cosecha y progreso.'),
  ('other', 'General', 'event-other', 'bg-secondary', '#6c757d', 90, 'Actividad general del sistema.', 'Evento no clasificado.');

-- Reglas de planeación por cultivo para generar calendario automáticamente.
CREATE TABLE IF NOT EXISTS crop_calendar_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  crop_name TEXT NOT NULL,
  event_type_slug TEXT NOT NULL,
  day_offset INTEGER NOT NULL,
  title_template TEXT NOT NULL,
  description_template TEXT NOT NULL,
  trigger_condition TEXT NOT NULL DEFAULT 'always',
  rationale TEXT,
  source_doc_hint TEXT,
  priority INTEGER NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(crop_name, event_type_slug, day_offset, title_template),
  FOREIGN KEY (event_type_slug) REFERENCES calendar_event_types(slug)
);

INSERT OR IGNORE INTO crop_calendar_rules
  (crop_name, event_type_slug, day_offset, title_template, description_template, trigger_condition, rationale, source_doc_hint, priority)
VALUES
  ('maiz', 'sowing', 0, 'Siembra de {crop_display}', 'Realizar siembra inicial del cultivo {crop_display}. Verificar humedad y profundidad de siembra.', 'always', 'Inicio del ciclo fenológico.', 'manual_maiz_milpa_2026', 10),
  ('maiz', 'monitoring', 7, 'Monitoreo temprano de {crop_display}', 'Revisar emergencia y vigor inicial. Registrar humedad de suelo y temperatura.', 'always', 'Validación de establecimiento temprano.', 'manual_maiz_milpa_2026', 20),
  ('maiz', 'fertilization', 18, 'Fertilización de arranque para {crop_display}', 'Aplicar ajuste nutricional inicial según condición del suelo y desarrollo vegetativo.', 'always', 'Soporte al desarrollo vegetativo temprano.', 'manual_maiz_milpa_2026', 30),
  ('maiz', 'maintenance', 25, 'Deshierbe y mantenimiento de {crop_display}', 'Controlar malezas y revisar cobertura para conservar humedad.', 'always', 'Reducción de competencia por agua y nutrientes.', 'manual_maiz_milpa_2026', 35),
  ('maiz', 'irrigation', 32, 'Riego programado de {crop_display}', 'Programar riego de soporte si humedad de suelo cae por debajo del rango objetivo.', 'soil_moisture_low', 'Evitar estrés hídrico en crecimiento activo.', 'manual_maiz_milpa_2026', 25),
  ('maiz', 'monitoring', 45, 'Monitoreo en floración de {crop_display}', 'Revisar temperatura alta, humedad y signos de estrés térmico en floración.', 'always', 'Etapa crítica para rendimiento.', 'manual_maiz_milpa_2026', 15),
  ('maiz', 'pest', 52, 'Inspección de plagas en {crop_display}', 'Inspeccionar presencia de plagas foliares y de mazorca; registrar hallazgos.', 'always', 'Prevención de pérdidas por plagas.', 'manual_maiz_milpa_2026', 18),
  ('maiz', 'irrigation', 60, 'Riego de soporte en llenado de grano ({crop_display})', 'Aplicar riego moderado para sostener llenado de grano sin encharcamiento.', 'soil_moisture_low', 'Soporte en fase de llenado.', 'manual_maiz_milpa_2026', 22),
  ('maiz', 'monitoring', 78, 'Monitoreo pre-cosecha de {crop_display}', 'Verificar madurez fisiológica, humedad de grano y estado sanitario.', 'always', 'Preparación para cosecha.', 'manual_maiz_milpa_2026', 16),
  ('maiz', 'harvest', 95, 'Cosecha estimada de {crop_display}', 'Planificar y ejecutar cosecha si la madurez del cultivo es adecuada.', 'always', 'Cierre de ciclo productivo.', 'manual_maiz_milpa_2026', 12),
  ('*', 'monitoring', 14, 'Monitoreo quincenal de {crop_display}', 'Revisar sensores, recomendaciones pendientes y estado general del cultivo.', 'always', 'Regla general para todo cultivo activo.', 'manual_operativo_milpa_2026', 40);

-- Catálogo de tipos de acción para recomendaciones (UI dinámica).
CREATE TABLE IF NOT EXISTS recommendation_action_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO recommendation_action_types (slug, label) VALUES
  ('riego', 'Riego'),
  ('fertilizacion', 'Fertilización'),
  ('plagas', 'Control de plagas'),
  ('siembra', 'Siembra'),
  ('cosecha', 'Cosecha'),
  ('monitoreo', 'Monitoreo');
