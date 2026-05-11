-- 0013_crop_profile_cycle_days.sql
-- Idempotente: añade `cycle_days` a crop_profiles para parametrizar el ciclo
-- típico del cultivo. Antes de esta migración el ciclo vivía como switch
-- hardcodeado en código (frontend Node y backend Python). Ahora cualquier
-- cultivo registrado en `crop_profiles` puede declarar su ciclo y el sistema
-- lo lee dinámicamente; los cultivos sin perfil caen a un fallback común.
--
-- Compatible con SQLite: ALTER TABLE ADD COLUMN sólo si no existe.

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

-- Idempotente: yoyo ejecuta el archivo entero en cada arranque, así que el
-- INSERT OR IGNORE no duplica filas y los UPDATE son seguros.
ALTER TABLE crop_profiles ADD COLUMN cycle_days INTEGER;

-- Defaults razonables por cultivo. Estos valores no son lógica de negocio:
-- son datos de referencia cargados como SEED y se pueden cambiar con un
-- UPDATE en runtime sin tocar el código.
UPDATE crop_profiles SET cycle_days = 120 WHERE crop_name = 'maiz' AND cycle_days IS NULL;
UPDATE crop_profiles SET cycle_days = 95  WHERE crop_name = 'frijol' AND cycle_days IS NULL;
UPDATE crop_profiles SET cycle_days = 105 WHERE crop_name = 'calabaza' AND cycle_days IS NULL;
UPDATE crop_profiles SET cycle_days = 125 WHERE crop_name = 'chile' AND cycle_days IS NULL;
UPDATE crop_profiles SET cycle_days = 130 WHERE crop_name = 'tomate' AND cycle_days IS NULL;
