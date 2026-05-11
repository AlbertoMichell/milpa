-- 0006_auth_chat_notifications.sql
-- Tablas para autenticación, chat en tiempo real y notificaciones.
-- Migra la funcionalidad que antes vivía en MongoDB al SQLite unificado.

-- Usuarios del sistema
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

-- Mensajes del chat en tiempo real
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  username TEXT NOT NULL,
  texto TEXT NOT NULL,
  type TEXT DEFAULT 'text' CHECK(type IN ('text','image','alert')),
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Notificaciones del sistema
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL CHECK(type IN ('alert','update','chat')),
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

-- Seed de notificaciones iniciales (solo si la tabla está vacía)
INSERT INTO notifications (type, title, message)
SELECT 'update', 'Version 1.1.0', 'Ya puedes registrar cultivos'
WHERE NOT EXISTS (SELECT 1 FROM notifications LIMIT 1);

INSERT INTO notifications (type, title, message)
SELECT 'alert', 'Mantenimiento', 'El sistema tendra downtime a las 22:00'
WHERE NOT EXISTS (SELECT 1 FROM notifications WHERE type='alert' AND title='Mantenimiento');

INSERT INTO notifications (type, title, message)
SELECT 'chat', 'Chat listo', 'Bienvenido al chat en vivo'
WHERE NOT EXISTS (SELECT 1 FROM notifications WHERE type='chat' AND title='Chat listo');

-- Índices
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);
