// server.js — Servidor frontend MILPA (SQLite, Socket.IO, AgroBot backend)
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
const NODE_ENV = process.env.NODE_ENV || 'development';
const IS_PROD = NODE_ENV === 'production';

const JWT_SECRET = process.env.JWT_SECRET || (IS_PROD ? null : '12345');
if (!JWT_SECRET) {
  throw new Error('JWT_SECRET es obligatorio en producción');
}

const SQLITE_PATH = path.resolve(
  __dirname,
  process.env.SQLITE_PATH || '../milpa_ai_backend/data/milpa_knowledge.db'
);
const AI_BACKEND = process.env.AI_BACKEND_URL || 'http://127.0.0.1:8000';
const PORT = Number(process.env.PORT || 4000);
const BODY_LIMIT = process.env.BODY_LIMIT || '1mb';
const AUTO_START_BACKEND = !IS_PROD && process.env.AUTO_START_BACKEND !== 'false';

const rawOrigins = process.env.FRONTEND_ORIGIN || '*';
const allowedOrigins = rawOrigins
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);
const corsOrigin = allowedOrigins.includes('*') ? '*' : allowedOrigins;
const corsOptions = {
  origin: corsOrigin,
  credentials: corsOrigin !== '*',
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
};

// --- Base de datos SQLite ---
const db = new Database(SQLITE_PATH);
db.pragma('journal_mode = WAL');
db.pragma('synchronous = NORMAL');

// Asegurar tablas propias del frontend.
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

// Migración defensiva para historial por usuario.
try {
  const cols = db.prepare('PRAGMA table_info(chat_messages)').all();
  const hasThreadUser = cols.some((c) => c.name === 'thread_user_id');
  if (!hasThreadUser) {
    db.exec('ALTER TABLE chat_messages ADD COLUMN thread_user_id INTEGER');
    db.exec('UPDATE chat_messages SET thread_user_id = user_id WHERE thread_user_id IS NULL');
  }
} catch (error) {
  console.warn('No se pudo ajustar esquema de chat_messages:', error.message);
}

// Seed de notificaciones iniciales.
try {
  const notifCount = db.prepare('SELECT COUNT(*) AS cnt FROM notifications').get().cnt;
  if (notifCount === 0) {
    const insert = db.prepare('INSERT INTO notifications (type, title, message) VALUES (?, ?, ?)');
    const seedMany = db.transaction((items) => {
      for (const n of items) insert.run(n.type, n.title, n.message);
    });
    seedMany([
      { type: 'update', title: 'Versión 1.1.0', message: '¡Ya puedes registrar cultivos!' },
      { type: 'alert', title: 'Mantenimiento', message: 'El sistema tendrá downtime a las 22:00' },
      { type: 'chat', title: 'Chat listo', message: 'Bienvenido al chat en vivo' },
    ]);
  }
} catch (error) {
  console.warn('No se pudieron inicializar notificaciones:', error.message);
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
  insertMessage: db.prepare(
    'INSERT INTO chat_messages (user_id, thread_user_id, username, texto, type) VALUES (?, ?, ?, ?, ?)'
  ),
  getMessageById: db.prepare('SELECT * FROM chat_messages WHERE id = ?'),
};

function normalizeChatText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 4000);
}

function safeUsername(socketUser) {
  return String(socketUser?.username || socketUser?.name || 'Usuario MILPA').trim().slice(0, 80);
}

// --- Express + Socket.IO ---
const app = express();
const server = http.createServer(app);
const io = socketio(server, {
  cors: {
    origin: corsOrigin,
    methods: ['GET', 'POST'],
    credentials: corsOrigin !== '*',
  },
});

app.use(cors(corsOptions));
app.use(express.json({ limit: BODY_LIMIT }));
app.use(express.urlencoded({ extended: true, limit: BODY_LIMIT }));
app.use(express.static(path.join(__dirname, 'MILPA')));
app.use('/api', require('./routes/api'));

// --- Chat AgroBot: frontend solo transporta; backend decide ---
async function responderComoBot(mensaje, usuarioId, usuarioNombre) {
  const BOT_ID = 0;

  const enqueue = (texto) => {
    const cleanText = String(texto || '').trim() || 'AgroBot no devolvió una respuesta válida.';
    setTimeout(() => {
      try {
        const botMsg = {
          usuarioId: String(BOT_ID),
          usuario: 'AgroBot',
          texto: cleanText,
          fecha: new Date().toISOString(),
        };
        io.to(`user:${usuarioId}`).emit('nuevo_mensaje', botMsg);
        stmts.insertMessage.run(null, Number(usuarioId), 'AgroBot', cleanText, 'text');
      } catch (error) {
        console.error('No se pudo guardar/enviar respuesta de AgroBot:', error);
      }
    }, 600);
  };

  const payload = {
    user_id: Number(usuarioId),
    username: usuarioNombre,
    message: normalizeChatText(mensaje),
    source: 'dashboard',
    mode: 'auto',
  };

  if (!payload.message) {
    enqueue('No entendí tu mensaje. Escribe una consulta sobre tus cultivos o sensores.');
    return;
  }

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
      const detail = data?.detail || `Backend respondió ${resp.status}`;
      enqueue(`Error al consultar AgroBot: ${detail}`);
      return;
    }

    enqueue(data?.answer);
  } catch (err) {
    enqueue(`Error al consultar AgroBot: ${err.message}`);
  }
}

// --- Autenticación Socket.IO ---
io.use((socket, next) => {
  const token = socket.handshake.auth?.token;
  if (!token) return next(new Error('Authentication error: No token provided'));

  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    socket.user = decoded.user;
    if (!socket.user?.id) return next(new Error('Authentication error: Invalid user payload'));
    next();
  } catch (err) {
    next(new Error('Authentication error: Invalid token'));
  }
});

io.on('connection', (socket) => {
  const userId = Number(socket.user.id);
  socket.join(`user:${userId}`);

  try {
    const notes = stmts.getNotifications.all();
    notes.reverse().forEach((n) => {
      socket.emit('push_notification', {
        type: n.type,
        title: n.title,
        message: n.message,
      });
    });
  } catch (e) {
    console.error('Error enviando notificaciones:', e);
  }

  socket.on('request_initial_data', () => {
    try {
      const msgs = stmts.getMessagesByThread.all(userId, userId);
      socket.emit(
        'data_update',
        msgs.map((m) => ({
          texto: m.texto,
          fecha: m.created_at,
          usuario: m.username,
          usuarioId: String(m.user_id),
        }))
      );
    } catch (e) {
      socket.emit('error_chat', { message: 'No se pudo cargar historial' });
    }
  });

  socket.on('mensaje_chat', async (data) => {
    try {
      const texto = normalizeChatText(data?.texto);
      if (!texto) {
        socket.emit('error_mensaje', { message: 'Mensaje vacío' });
        return;
      }

      const username = safeUsername(socket.user);
      const result = stmts.insertMessage.run(userId, userId, username, texto, 'text');
      const saved = stmts.getMessageById.get(result.lastInsertRowid);

      io.to(`user:${userId}`).emit('nuevo_mensaje', {
        usuarioId: String(saved.user_id),
        usuario: saved.username,
        texto: saved.texto,
        fecha: saved.created_at,
      });

      await responderComoBot(saved.texto, userId, username);
    } catch (err) {
      console.error('Error procesando mensaje_chat:', err);
      socket.emit('error_mensaje', { message: 'Error al procesar mensaje' });
    }
  });
});

server.listen(PORT, () => console.log(`Servidor en http://localhost:${PORT}`));

// --- Auto-inicio del backend IA: solo desarrollo ---
let _backendChild = null;

function checkPort8000() {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(1500);
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('error', () => {
      socket.destroy();
      resolve(false);
    });
    socket.once('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.connect(8000, '127.0.0.1');
  });
}

async function ensureBackend() {
  const running = await checkPort8000();
  if (running) return console.log('Backend IA ya activo en puerto 8000');

  console.log('Iniciando backend IA...');
  const backendDir = path.resolve(__dirname, '../milpa_ai_backend');
  const pyExe = process.platform === 'win32' ? 'py' : 'python3';

  _backendChild = spawn(
    pyExe,
    ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'],
    { cwd: backendDir, stdio: 'pipe' }
  );

  _backendChild.stderr.on('data', (chunk) => {
    console.error(`[backend] ${String(chunk).trim()}`);
  });

  let ok = false;
  for (let i = 0; i < 8; i += 1) {
    await new Promise((r) => setTimeout(r, 1000));
    ok = await checkPort8000();
    if (ok) break;
  }

  console.log(ok ? 'Backend IA iniciado correctamente' : 'Backend IA puede no estar disponible aún');
}

if (AUTO_START_BACKEND) {
  ensureBackend().catch((err) => console.error('Error iniciando backend:', err));
}

function shutdown() {
  try {
    db.close();
  } catch (_) {}
  if (_backendChild) _backendChild.kill();
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
