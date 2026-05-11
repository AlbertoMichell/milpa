-- 0008_edaphology_global.sql
-- Base edafológica general + perfiles de cultivo para recomendaciones contextuales.

CREATE TABLE IF NOT EXISTS edaphology_global_readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  location_name TEXT DEFAULT 'general',
  soil_temp REAL,
  air_temp REAL,
  air_humidity REAL,
  soil_moisture REAL,
  precipitation REAL,
  wind_speed REAL,
  ph REAL,
  conductivity REAL,
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_edaphology_global_created_at ON edaphology_global_readings(created_at);

CREATE TABLE IF NOT EXISTS crop_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  crop_name TEXT NOT NULL UNIQUE,
  variety TEXT,
  optimal_temp_min REAL,
  optimal_temp_max REAL,
  optimal_soil_moisture_min REAL,
  optimal_soil_moisture_max REAL,
  optimal_air_humidity_min REAL,
  optimal_air_humidity_max REAL,
  optimal_ph_min REAL,
  optimal_ph_max REAL,
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- Dataset base de perfiles agronómicos.
INSERT OR IGNORE INTO crop_profiles (
  crop_name, variety, optimal_temp_min, optimal_temp_max,
  optimal_soil_moisture_min, optimal_soil_moisture_max,
  optimal_air_humidity_min, optimal_air_humidity_max,
  optimal_ph_min, optimal_ph_max, notes
) VALUES
  ('maiz', 'Criollo', 18, 32, 45, 75, 40, 70, 5.5, 7.5, 'Cultivo de ciclo intermedio, sensible a calor extremo en floración.'),
  ('frijol', 'Negro', 16, 30, 40, 70, 45, 75, 5.8, 7.2, 'Fijador de N; exceso de humedad favorece enfermedades de raíz.'),
  ('calabaza', NULL, 20, 34, 50, 80, 50, 80, 6.0, 7.5, 'Alta demanda hídrica durante floración y llenado de fruto.'),
  ('chile', 'Serrano', 20, 33, 35, 65, 30, 65, 6.0, 7.0, 'Planta ejemplo: sensible a golpes de calor >35C y estrés hídrico.'),
  ('tomate', NULL, 18, 30, 45, 70, 50, 75, 5.8, 7.0, 'Riesgo de aborto floral con calor sostenido >32C.');

-- Lectura global inicial.
INSERT INTO edaphology_global_readings (
  location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes
)
SELECT
  'general', 24.0, 28.0, 55.0, 58.0, 0.0, 8.0, 6.5, 1.1,
  'Base inicial edafológica general para contextualizar recomendaciones.'
WHERE NOT EXISTS (SELECT 1 FROM edaphology_global_readings);
