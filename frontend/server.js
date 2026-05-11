// server.js — Servidor frontend MILPA (SQLite, sin MongoDB)
require('dotenv').config();
const express = require('express');
const Database = require('better-sqlite3');
const socketio = require('socket.io');
const http = require('http');
const path = require('path');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const { spawn } = require('child_process');
const net = require('net');

// --- Configuración ---
const JWT_SECRET = process.env.JWT_SECRET || '12345';
const SQLITE_PATH = path.resolve(__dirname, process.env.SQLITE_PATH || '../milpa_ai_backend/data/milpa_knowledge.db');
const AI_BACKEND = process.env.AI_BACKEND_URL || 'http://127.0.0.1:8000';

// --- Base de datos SQLite ---
const db = new Database(SQLITE_PATH);
db.pragma('journal_mode = WAL');
db.pragma('synchronous = NORMAL');

// Asegurar tablas
db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
  );
  CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    thread_user_id INTEGER,
    username TEXT NOT NULL,
    texto TEXT NOT NULL,
    type TEXT DEFAULT 'text' CHECK(type IN ('text','image','alert')),
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
  );
  CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('alert','update','chat')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
  );
`);

// Migración defensiva
try {
  const cols = db.prepare("PRAGMA table_info(chat_messages)").all();
  const hasThreadUser = cols.some(c => c.name === 'thread_user_id');
  if (!hasThreadUser) {
    db.exec("ALTER TABLE chat_messages ADD COLUMN thread_user_id INTEGER");
    db.exec("UPDATE chat_messages SET thread_user_id = user_id WHERE thread_user_id IS NULL");
  }
} catch (error) {
  console.warn('No se pudo ajustar esquema de chat_messages:', error.message);
}

// Seed notificaciones
const notifCount = db.prepare('SELECT COUNT(*) AS cnt FROM notifications').get().cnt;
if (notifCount === 0) {
  const insert = db.prepare('INSERT INTO notifications (type, title, message) VALUES (?, ?, ?)');
  const seedMany = db.transaction((items) => {
    for (const n of items) insert.run(n.type, n.title, n.message);
  });
  seedMany([
    { type: 'update', title: 'Versión 1.1.0', message: '¡Ya puedes registrar cultivos!' },
    { type: 'alert',  title: 'Mantenimiento',  message: 'El sistema tendrá downtime a las 22:00' },
    { type: 'chat',   title: 'Chat listo',     message: 'Bienvenido al chat en vivo' }
  ]);
}

console.log('SQLite conectado:', SQLITE_PATH);

// --- Prepared statements ---
const stmts = {
  getNotifications: db.prepare('SELECT * FROM notifications ORDER BY created_at DESC LIMIT 3'),
  getMessagesByThread: db.prepare(`
    SELECT *
    FROM chat_messages
    WHERE thread_user_id = ?
       OR (thread_user_id IS NULL AND user_id = ?)
       OR (thread_user_id IS NULL AND user_id = 0)
    ORDER BY created_at ASC
    LIMIT 250
  `),
  insertMessage:   db.prepare('INSERT INTO chat_messages (user_id, thread_user_id, username, texto, type) VALUES (?, ?, ?, ?, ?)'),
  getMessageById:  db.prepare('SELECT * FROM chat_messages WHERE id = ?'),
};
// --- Chat AgroBot (backend) ---
async function responderComoBot(mensaje, usuarioId, usuarioNombre) {
  const BOT_ID = 0;
  const enqueue = (texto) => {
    setTimeout(() => {
      const botMsg = { usuarioId: String(BOT_ID), usuario: 'AgroBot', texto, fecha: new Date().toISOString() };
      io.to(`user:${usuarioId}`).emit('nuevo_mensaje', botMsg);
      stmts.insertMessage.run(null, usuarioId, 'AgroBot', texto, 'text');
    }, 600);
  };

  const payload = {
    user_id: Number(usuarioId),
    username: usuarioNombre,
    message: String(mensaje || ''),
    source: 'dashboard',
    mode: 'auto',
  };

  try {
    const resp = await fetch(`${AI_BACKEND}/api/agrobot/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    let data = null;
    try {
      data = await resp.json();
    } catch (_) {
      data = null;
    }

    if (!resp.ok) {
      const detail = data?.detail || `Backend respondio ${resp.status}`;
      enqueue(`Error al consultar AgroBot: ${detail}`);
      return;
    }

    const answer = String(data?.answer || '').trim();
    enqueue(answer || 'AgroBot no devolvio una respuesta valida.');
  } catch (err) {
    enqueue(`Error al consultar AgroBot: ${err.message}`);
  }
}

// --- Express + Socket.IO ---
const app = express();
const server = http.createServer(app);
const io = socketio(server, { cors: { origin: '*', methods: ['GET','POST'] } });
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'MILPA')));
app.use('/api', require('./routes/api'));

io.use((socket, next) => {
  const token = socket.handshake.auth.token;
  if (!token) return next(new Error('Authentication error: No token provided'));
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    socket.user = decoded.user;
    next();
  } catch (err) {
    next(new Error('Authentication error: Invalid token'));
  }
});

io.on('connection', socket => {
  socket.join(`user:${socket.user.id}`);
  try {
    const notes = stmts.getNotifications.all();
    notes.reverse().forEach(n => socket.emit('push_notification', { type: n.type, title: n.title, message: n.message }));
  } catch (e) { console.error('Error enviando notificaciones:', e); }

  socket.on('request_initial_data', () => {
    try {
      const msgs = stmts.getMessagesByThread.all(Number(socket.user.id), Number(socket.user.id));
      socket.emit('data_update', msgs.map(m => ({
        texto: m.texto, fecha: m.created_at, usuario: m.username, usuarioId: String(m.user_id)
      })));
    } catch (e) { socket.emit('error_chat', { message: 'No se pudo cargar historial' }); }
  });

  socket.on('mensaje_chat', async (data) => {
    try {
      const result = stmts.insertMessage.run(socket.user.id, socket.user.id, socket.user.username, data.texto, 'text');
      const saved = stmts.getMessageById.get(result.lastInsertRowid);
      io.to(`user:${socket.user.id}`).emit('nuevo_mensaje', {
        usuarioId: String(saved.user_id), usuario: saved.username, texto: saved.texto, fecha: saved.created_at
      });
      await responderComoBot(saved.texto, socket.user.id, socket.user.username);
    } catch (err) {
      socket.emit('error_mensaje', { message: 'Error al procesar mensaje' });
    }
  });

  socket.on('disconnect', () => {});
});

const PORT = process.env.PORT || 4000;
server.listen(PORT, () => console.log(`Servidor en http://localhost:${PORT}`));

// --- Auto-inicio del backend IA (opcional) ---
let _backendChild = null;
function checkPort8000() {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(1500);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('error', () => { socket.destroy(); resolve(false); });
    socket.once('timeout', () => { socket.destroy(); resolve(false); });
    socket.connect(8000, '127.0.0.1');
  });
}
async function ensureBackend() {
  const running = await checkPort8000();
  if (running) return console.log('Backend IA ya activo en puerto 8000');
  console.log('Iniciando backend IA...');
  const backendDir = path.resolve(__dirname, '../milpa_ai_backend');
  const pyExe = process.platform === 'win32' ? 'py' : 'python3';
  _backendChild = spawn(pyExe, ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], { cwd: backendDir, stdio: 'pipe' });
  let ok = false;
  for (let i = 0; i < 8; i++) { await new Promise(r => setTimeout(r, 1000)); ok = await checkPort8000(); if (ok) break; }
  console.log(ok ? 'Backend IA iniciado correctamente' : 'Backend IA puede no estar disponible aún');
}
ensureBackend().catch(err => console.error('Error iniciando backend:', err));

process.on('SIGINT', () => { db.close(); if (_backendChild) _backendChild.kill(); process.exit(0); });
process.on('SIGTERM', () => { db.close(); if (_backendChild) _backendChild.kill(); process.exit(0); });