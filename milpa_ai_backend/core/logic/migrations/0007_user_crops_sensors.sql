-- 0007_user_crops_sensors.sql
-- Tablas para cultivos del usuario, lecturas de sensores y recomendaciones generadas.

-- Cultivos registrados por el agricultor
CREATE TABLE IF NOT EXISTS user_crops (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  crop_name TEXT NOT NULL,          -- ej: 'chile', 'maiz', 'frijol'
  variety TEXT,                     -- ej: 'Criollo', 'Negro', 'Serrano'
  planted_at TEXT,                  -- fecha de siembra ISO
  status TEXT DEFAULT 'activo' CHECK(status IN ('activo','cosechado','perdido')),
  progress INTEGER DEFAULT 0,      -- porcentaje 0-100
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Lecturas de sensores (historico)
CREATE TABLE IF NOT EXISTS sensor_readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_crop_id INTEGER NOT NULL,
  soil_moisture REAL,        -- % humedad suelo
  air_temp REAL,             -- grados C
  air_humidity REAL,         -- % humedad aire
  light REAL,                -- % luz solar
  precipitation REAL,        -- mm lluvia
  wind_speed REAL,           -- km/h
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_crop_id) REFERENCES user_crops(id)
);

-- Recomendaciones generadas por el sistema RAG
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_crop_id INTEGER NOT NULL,
  query_text TEXT NOT NULL,         -- pregunta generada
  action TEXT NOT NULL,             -- accion resumida: 'regar', 'fertilizar', 'cosechar', etc.
  priority TEXT DEFAULT 'medium' CHECK(priority IN ('high','medium','low')),
  detail_html TEXT,                 -- respuesta completa del RAG
  citations TEXT,                   -- JSON array de citas
  status TEXT DEFAULT 'pendiente' CHECK(status IN ('pendiente','aplicada','pospuesta')),
  faithfulness REAL,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_crop_id) REFERENCES user_crops(id)
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_user_crops_user ON user_crops(user_id);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_crop ON sensor_readings(user_crop_id);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_time ON sensor_readings(created_at);
CREATE INDEX IF NOT EXISTS idx_recommendations_crop ON recommendations(user_crop_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON recommendations(status);

-- Seed: cultivos de ejemplo para el usuario testuser (id=1)
INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress)
SELECT 1, 'maiz', 'Criollo', '2025-02-15', 'activo', 65
WHERE NOT EXISTS (SELECT 1 FROM user_crops WHERE user_id=1 AND crop_name='maiz');

INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress)
SELECT 1, 'frijol', 'Negro', '2025-05-22', 'activo', 45
WHERE NOT EXISTS (SELECT 1 FROM user_crops WHERE user_id=1 AND crop_name='frijol');

INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress)
SELECT 1, 'calabaza', NULL, '2025-06-10', 'activo', 30
WHERE NOT EXISTS (SELECT 1 FROM user_crops WHERE user_id=1 AND crop_name='calabaza');

INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress)
SELECT 1, 'chile', 'Serrano', '2025-06-05', 'activo', 20
WHERE NOT EXISTS (SELECT 1 FROM user_crops WHERE user_id=1 AND crop_name='chile');

INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress)
SELECT 1, 'tomate', NULL, '2025-06-12', 'activo', 55
WHERE NOT EXISTS (SELECT 1 FROM user_crops WHERE user_id=1 AND crop_name='tomate');

-- Seed: lecturas iniciales de sensores
INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation)
SELECT 1, 64.0, 26.0, 55.0, 78.0, 0.0
WHERE NOT EXISTS (SELECT 1 FROM sensor_readings WHERE user_crop_id=1);

INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation)
SELECT 2, 42.0, 28.0, 48.0, 72.0, 2.0
WHERE NOT EXISTS (SELECT 1 FROM sensor_readings WHERE user_crop_id=2);

INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation)
SELECT 3, 58.0, 25.0, 60.0, 80.0, 0.0
WHERE NOT EXISTS (SELECT 1 FROM sensor_readings WHERE user_crop_id=3);

INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation)
SELECT 4, 13.0, 35.0, 28.0, 85.0, 0.0
WHERE NOT EXISTS (SELECT 1 FROM sensor_readings WHERE user_crop_id=4);

INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation)
SELECT 5, 50.0, 27.0, 52.0, 75.0, 1.5
WHERE NOT EXISTS (SELECT 1 FROM sensor_readings WHERE user_crop_id=5);
