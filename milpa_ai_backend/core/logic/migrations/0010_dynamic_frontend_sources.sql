-- 0010_dynamic_frontend_sources.sql
-- ----------------------------------------------------------------------
-- Cierra los gaps de auditoría del frontend MILPA:
--  · Notificaciones por usuario y cultivo.
--  · Geolocalización de la finca (mapa del dashboard).
--  · Posición XY del sensor de cada cultivo (mapa de tiempo-real).
--  · Óptimos de riego y radar por cultivo (panel de datos).
--  · Tablas faqs y library_categories para sustituir contenidos literales.
-- ----------------------------------------------------------------------

-- 1) NOTIFICATIONS por usuario (gap G1) ---------------------------------
ALTER TABLE notifications ADD COLUMN user_id INTEGER;
ALTER TABLE notifications ADD COLUMN user_crop_id INTEGER;
ALTER TABLE notifications ADD COLUMN link_url TEXT;
ALTER TABLE notifications ADD COLUMN read_at TEXT;

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_crop ON notifications(user_crop_id);

-- 2) GEO en user_profiles (gap G2) -------------------------------------
ALTER TABLE user_profiles ADD COLUMN lat REAL;
ALTER TABLE user_profiles ADD COLUMN lon REAL;
ALTER TABLE user_profiles ADD COLUMN geo_zoom INTEGER DEFAULT 14;

UPDATE user_profiles
SET lat = -19.4517, lon = -96.9612, geo_zoom = 14
WHERE lat IS NULL;

-- 3) Posición XY del sensor por cultivo (gap G3) -----------------------
ALTER TABLE user_crops ADD COLUMN sensor_x_pct REAL;
ALTER TABLE user_crops ADD COLUMN sensor_y_pct REAL;

UPDATE user_crops
SET sensor_x_pct = CASE (id % 4)
        WHEN 0 THEN 0.25
        WHEN 1 THEN 0.70
        WHEN 2 THEN 0.30
        ELSE        0.80
    END,
    sensor_y_pct = CASE (id % 4)
        WHEN 0 THEN 0.30
        WHEN 1 THEN 0.20
        WHEN 2 THEN 0.75
        ELSE        0.70
    END
WHERE sensor_x_pct IS NULL OR sensor_y_pct IS NULL;

-- 4) Óptimos de riego + radar por cultivo (gap G4) ---------------------
ALTER TABLE crop_profiles ADD COLUMN optimal_irrigation_liters REAL;
ALTER TABLE crop_profiles ADD COLUMN optimal_irrigation_freq_per_month REAL;
ALTER TABLE crop_profiles ADD COLUMN optimal_irrigation_duration_min REAL;
ALTER TABLE crop_profiles ADD COLUMN expected_irrigation_delta_pct REAL;
ALTER TABLE crop_profiles ADD COLUMN optimal_radar_json TEXT;

UPDATE crop_profiles
SET optimal_irrigation_liters = 45.0,
    optimal_irrigation_freq_per_month = 4.0,
    optimal_irrigation_duration_min = 35.0,
    expected_irrigation_delta_pct = 12.0,
    optimal_radar_json = '[90,85,95,90,95]'
WHERE crop_name = 'maiz';

UPDATE crop_profiles
SET optimal_irrigation_liters = 35.0,
    optimal_irrigation_freq_per_month = 5.0,
    optimal_irrigation_duration_min = 30.0,
    expected_irrigation_delta_pct = 10.0,
    optimal_radar_json = '[85,80,90,85,90]'
WHERE crop_name = 'frijol';

UPDATE crop_profiles
SET optimal_irrigation_liters = 60.0,
    optimal_irrigation_freq_per_month = 6.0,
    optimal_irrigation_duration_min = 40.0,
    expected_irrigation_delta_pct = 14.0,
    optimal_radar_json = '[92,82,95,90,95]'
WHERE crop_name = 'calabaza';

UPDATE crop_profiles
SET optimal_irrigation_liters = 30.0,
    optimal_irrigation_freq_per_month = 6.0,
    optimal_irrigation_duration_min = 25.0,
    expected_irrigation_delta_pct = 9.0,
    optimal_radar_json = '[80,80,85,90,85]'
WHERE crop_name = 'chile';

UPDATE crop_profiles
SET optimal_irrigation_liters = 40.0,
    optimal_irrigation_freq_per_month = 7.0,
    optimal_irrigation_duration_min = 30.0,
    expected_irrigation_delta_pct = 11.0,
    optimal_radar_json = '[88,82,90,90,90]'
WHERE crop_name = 'tomate';

-- 5) Tabla FAQs (gap G5) -----------------------------------------------
CREATE TABLE IF NOT EXISTS faqs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  crop_name TEXT,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  related_doc_id TEXT,
  priority INTEGER DEFAULT 100,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (related_doc_id) REFERENCES docs(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_faqs_category ON faqs(category);
CREATE INDEX IF NOT EXISTS idx_faqs_crop ON faqs(crop_name);

INSERT OR IGNORE INTO faqs (id, category, crop_name, question, answer, priority) VALUES
  (1, 'siembra', 'maiz',
   '¿Cuál es el mejor momento para sembrar maíz?',
   'Siembra cuando el suelo se sostiene a 18 °C o más durante al menos cinco días seguidos. En la milpa tradicional mexicana esto coincide con el inicio de la temporada de lluvias (abril–junio según la región). Espera a tener entre 45 % y 75 % de humedad de suelo antes de depositar la semilla.',
   10),
  (2, 'plagas', NULL,
   '¿Cómo controlar plagas sin químicos?',
   'Aplica el principio de la milpa: rota maíz–frijol–calabaza para romper ciclos de plagas, instala trampas amarillas pegantes, libera enemigos naturales (Trichogramma, mariquitas) y usa biocontroladores como Beauveria bassiana. Solo si superas el umbral de daño (>3 individuos por planta) intervén con extracto de neem o ajo.',
   20),
  (3, 'sistema', NULL,
   '¿Qué beneficios tiene el sistema MILPA tradicional?',
   'La milpa fija nitrógeno biológicamente (frijol), retiene humedad y suprime malezas (calabaza), aprovecha la estructura del maíz como tutor y genera una dieta nutricionalmente completa. Reduce hasta 60 % el uso de fertilizantes sintéticos y aumenta la resiliencia frente a sequía respecto a un monocultivo.',
   30),
  (4, 'riego', 'maiz',
   '¿Cuánta agua necesita el maíz en floración?',
   'En la fase de floración (V12–R1) el maíz exige entre 35 y 45 mm semanales y no tolera estrés hídrico de más de 48 h. Mantén la humedad del suelo entre 55 % y 70 %; por debajo de 30 % aplica riego por goteo de inmediato.',
   40),
  (5, 'fertilizacion', 'maiz',
   '¿Cómo se fertiliza el maíz en suelo arcilloso?',
   'Aplica una primera dosis de N en V4 (≈40 kg/ha urea fraccionada), una segunda en V8 (≈40 kg/ha) y refuerza P y K en función del análisis de suelo. En arcillosos prefiere fuentes de liberación lenta y evita aplicar antes de lluvias intensas para reducir lixiviación.',
   50),
  (6, 'cosecha', 'maiz',
   '¿Cuándo cosechar maíz para grano?',
   'Cosecha cuando el grano alcanza 18–22 % de humedad y aparece la “capa negra” en la base del grano. Para forraje cosecha en estado lechoso–masoso. Si la humedad supera 25 %, requerirás secado artificial para almacenamiento seguro.',
   60),
  (7, 'monitoreo', NULL,
   '¿Qué variables debo monitorear día a día?',
   'Humedad de suelo (objetivo 45–75 %), temperatura del aire (alarma >35 °C), humedad ambiental, conteo de plagas y precipitación. MILPA agrupa estas señales y genera una recomendación priorizada cada vez que se cruzan los umbrales del cultivo.',
   70),
  (8, 'agua', NULL,
   '¿Cómo manejar el agua en milpa de temporal?',
   'Combina captación con bordos de contorno, acolchado vegetal sobre la línea de siembra y siembra escalonada para distribuir riesgo. Durante canícula prioriza riego de auxilio en cultivos en floración (maíz) y suspende riego cuando la precipitación supere 25 mm en 24 h.',
   80);

-- 6) Tabla library_categories (gap G6) ---------------------------------
CREATE TABLE IF NOT EXISTS library_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT,
  query_example TEXT,
  icon TEXT,
  priority INTEGER DEFAULT 100,
  created_at TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO library_categories (id, slug, title, description, query_example, icon, priority) VALUES
  (1, 'siembra',     'Técnicas de siembra',  'Métodos tradicionales y modernos para preparar suelo y sembrar', 'tecnicas de siembra milpa maiz frijol calabaza', 'bi-tree-fill',           10),
  (2, 'plagas',      'Control de plagas',     'Manejo integrado y métodos orgánicos contra plagas comunes',     'control biologico plagas maiz frijol calabaza',  'bi-bug-fill',            20),
  (3, 'agua',        'Manejo del agua',       'Técnicas de captación, conservación y riego eficiente',           'manejo hidrico riego goteo milpa cosecha agua',  'bi-droplet-fill',        30),
  (4, 'calendario',  'Calendario lunar',      'Influencia lunar y temporadas óptimas para cada actividad',       'calendario lunar siembra cosecha milpa',         'bi-moon-stars-fill',     40);

-- 7) Reset notifications "globales" para que pertenezcan al primer usuario --
UPDATE notifications
SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
WHERE user_id IS NULL;
