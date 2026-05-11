-- 0009_frontend_connected_features.sql
-- Persistencia para metadatos visibles del cultivo, perfil, ajustes y calendario.

ALTER TABLE user_crops ADD COLUMN display_name TEXT;
ALTER TABLE user_crops ADD COLUMN image_path TEXT;
ALTER TABLE user_crops ADD COLUMN growth_stage TEXT;
ALTER TABLE user_crops ADD COLUMN expected_harvest_at TEXT;

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id INTEGER PRIMARY KEY,
  first_name TEXT,
  last_name TEXT,
  bio TEXT,
  location TEXT,
  experience TEXT,
  avatar_path TEXT,
  email TEXT,
  phone TEXT,
  language TEXT DEFAULT 'Español',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY,
  email_alerts INTEGER DEFAULT 1,
  daily_summary INTEGER DEFAULT 1,
  weekly_report INTEGER DEFAULT 0,
  push_alerts INTEGER DEFAULT 1,
  push_recommendations INTEGER DEFAULT 1,
  push_reminders INTEGER DEFAULT 0,
  notification_frequency TEXT DEFAULT 'inmediata',
  min_soil_moisture INTEGER DEFAULT 40,
  max_temperature INTEGER DEFAULT 35,
  min_air_humidity INTEGER DEFAULT 50,
  pest_threshold INTEGER DEFAULT 3,
  alert_water INTEGER DEFAULT 1,
  alert_temp INTEGER DEFAULT 1,
  alert_pests INTEGER DEFAULT 1,
  alert_growth INTEGER DEFAULT 0,
  alert_weather INTEGER DEFAULT 1,
  data_collection INTEGER DEFAULT 1,
  research_participation INTEGER DEFAULT 0,
  location_sharing INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS calendar_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  user_crop_id INTEGER,
  title TEXT NOT NULL,
  event_type TEXT NOT NULL DEFAULT 'other',
  start_date TEXT NOT NULL,
  end_date TEXT,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'programado' CHECK(status IN ('programado', 'completado', 'cancelado')),
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (user_crop_id) REFERENCES user_crops(id)
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_date);

UPDATE user_crops
SET display_name = CASE
  WHEN COALESCE(TRIM(variety), '') <> '' THEN UPPER(SUBSTR(crop_name, 1, 1)) || SUBSTR(crop_name, 2) || ' ' || TRIM(variety)
  ELSE UPPER(SUBSTR(crop_name, 1, 1)) || SUBSTR(crop_name, 2)
END
WHERE display_name IS NULL;

UPDATE user_crops
SET growth_stage = CASE
  WHEN progress >= 75 THEN 'maduración'
  WHEN progress >= 45 THEN 'desarrollo'
  WHEN progress >= 20 THEN 'establecimiento'
  ELSE 'siembra'
END
WHERE growth_stage IS NULL;

UPDATE user_crops
SET expected_harvest_at = date(planted_at, '+120 days')
WHERE expected_harvest_at IS NULL AND planted_at IS NOT NULL;

INSERT INTO user_settings (user_id)
SELECT id FROM users
WHERE NOT EXISTS (SELECT 1 FROM user_settings WHERE user_id = users.id);

INSERT INTO user_profiles (user_id, first_name)
SELECT id, username FROM users
WHERE NOT EXISTS (SELECT 1 FROM user_profiles WHERE user_id = users.id);