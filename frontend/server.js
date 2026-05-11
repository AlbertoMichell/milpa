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

// --- Utilidades universales ---
function htmlToPlainText(html) {
  return String(html || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<li>/gi, '- ')
    .replace(/<\/li>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function formatIsoDate(value) {
  if (!value) return null;
  const s = String(value).trim();
  if (!s) return null;
  return s.slice(0, 10);
}

function normalizeCropName(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim();
}

function cropDisplayLabel(crop) {
  return crop?.display_name || crop?.crop_name || 'cultivo activo';
}

function getCropProfileFor(crop) {
  const name = normalizeCropName(crop?.crop_name || '');
  if (!name) return null;
  try {
    return db.prepare(`
      SELECT crop_name,
             optimal_soil_moisture_min AS soil_moisture_min,
             optimal_soil_moisture_max AS soil_moisture_max,
             optimal_temp_min AS temp_min,
             optimal_temp_max AS temp_max
      FROM crop_profiles
      WHERE LOWER(crop_name) = ?
      LIMIT 1
    `).get(name);
  } catch (_) { return null; }
}

// --- Detección de intenciones ---
function isWaterBalanceQuery(message) {
  const m = normalizeCropName(message);
  if (!m || m.length < 3) return false;
  return /\b(agua|humedad(\s+(del\s+)?suelo)?|riego(s)?|regar|rieg(o|a|amos|uen)?|como\s+estoy\s+de\s+agua|estoy\s+de\s+agua)\b/.test(m);
}

function isLowConfidenceChatInput(message) {
  const raw = String(message || '').trim();
  if (!raw) return true;
  const letters = (raw.match(/[a-záéíóúñ]/gi) || []).length;
  if (letters / Math.max(raw.length, 1) < 0.4) return true;
  if (/^(.)\1{5,}$/i.test(raw)) return true;
  if (/^(dadad|abab|asdf|qwert|xxxxx)/i.test(raw)) return true;
  if (raw.length <= 3 && !/\d/.test(raw)) return true;
  return false;
}

const _chatRepeatTs = new Map();
function shouldThrottleDuplicateChat(userId, message) {
  const key = `${userId}::${normalizeCropName(message)}`;
  const now = Date.now();
  const prev = _chatRepeatTs.get(key);
  _chatRepeatTs.set(key, now);
  return Boolean(prev && now - prev < 28000);
}

function chatGarbageReply() {
  return 'No entendí tu mensaje. Probá con el nombre de un cultivo activo o una consulta como "¿cómo estoy de agua?" o "plagas en el maíz".';
}

// --- Detección de cultivo en mensaje ---
let _chatKnownCropsCache = null;
let _chatKnownCropsCacheAt = 0;
function chatKnownCrops() {
  const now = Date.now();
  if (_chatKnownCropsCache && now - _chatKnownCropsCacheAt < 30000) return _chatKnownCropsCache;
  try {
    const rows = db.prepare('SELECT LOWER(crop_name) AS name FROM crop_profiles').all();
    _chatKnownCropsCache = rows.map(r => r.name).filter(Boolean);
  } catch (_e) {
    _chatKnownCropsCache = [];
  }
  _chatKnownCropsCacheAt = now;
  return _chatKnownCropsCache;
}

function detectRequestedCrop(message, userCropRows = null) {
  const txt = normalizeCropName(message);
  if (!txt) return null;
  const known = chatKnownCrops();
  let best = null;
  let bestLen = 0;
  for (const c of known) {
    if (!c || c.length < 2) continue;
    if (txt.includes(c) && c.length > bestLen) {
      best = c;
      bestLen = c.length;
    }
  }
  // ignorar falsos positivos de agua
  if (best && isWaterBalanceQuery(message) && ['agua','humedad','sequia','lluvia','riego','riegos','precipitacion'].includes(best)) {
    best = null;
  }
  if (userCropRows?.length) {
    for (const row of userCropRows) {
      const variants = cropNameVariants(row);
      for (const n of variants) {
        if (n.length >= 2 && txt.includes(n) && n.length > bestLen) {
          best = n;
          bestLen = n.length;
        }
      }
    }
  }
  return best;
}

function cropNameVariants(crop) {
  return [crop?.crop_name, crop?.display_name, crop?.variety].filter(Boolean).map(normalizeCropName).filter(Boolean);
}

function matchRequestedToActiveCrop(requested, activeCrops = []) {
  if (!requested) return null;
  const req = normalizeCropName(requested);
  for (const crop of activeCrops) {
    if (cropNameVariants(crop).includes(req)) return crop;
  }
  return null;
}

// --- Construcción de contexto ---
function buildChatQuery(message, userId) {
  let crops = [];
  let globalReading = null;
  try {
    crops = db.prepare(`
      SELECT c.id, c.crop_name, c.display_name, c.variety, c.growth_stage,
             c.planted_at, c.expected_harvest_at, c.status, c.progress,
             (SELECT sr.soil_moisture FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS soil_moisture,
             (SELECT sr.air_temp FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS air_temp,
             (SELECT sr.air_humidity FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS air_humidity,
             (SELECT sr.light FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS light
      FROM user_crops c
      WHERE c.user_id = ?
      ORDER BY c.created_at DESC LIMIT 5
    `).all(userId);
  } catch (e) { console.warn('Error cargando crops:', e.message); }
  try {
    globalReading = db.prepare(`
      SELECT location_name, air_temp, soil_moisture, air_humidity, precipitation, wind_speed, ph, conductivity, created_at
      FROM edaphology_global_readings ORDER BY created_at DESC LIMIT 1
    `).get();
  } catch (e) { console.warn('Error cargando edafología:', e.message); }
  return { rawMessage: message, crops, globalReading };
}

// --- Extracción limpia de respuesta RAG (Bloqueo de alucinaciones) ---
function extractRagAnswer(ragPayloadJson) {
  if (!ragPayloadJson || !ragPayloadJson.answer) return null;
  
  // Usamos el flag del backend para evitar basura ("lluvia", "calor")
  if (ragPayloadJson.insufficient_evidence === true || ragPayloadJson.answer_mode === 'insufficient') {
    return null;
  }

  let text = htmlToPlainText(ragPayloadJson.answer);
  const cut = text.search(/\n\s*Fuentes:\s*/i);
  if (cut >= 0) text = text.slice(0, cut).trim();
  
  // Limpieza de prefijos base
  text = text.replace(/^Pasos y recomendaciones para «[^»]+»:\s*/i, '');
  text = text.replace(/^Hallazgos en la biblioteca para «[^»]+»:\s*/i, '');
  text = text.replace(/^Par[áa]metros agron[óo]micos relevantes para «[^»]+»:\s*/i, '');
  text = text.replace(/^Informaci[oó]n encontrada relacionada con «[^»]+»:\s*/i, '');
  text = text.replace(/^Definici[oó]n de «[^»]+»:\s*/i, '');
  
  return text.trim();
}

// --- Limpieza del detalle del motor ---
function cleanMotorDetail(detail) {
  if (!detail) return '';
  let t = String(detail).replace(/\s+/g, ' ').trim();
  t = t.replace(/^Par[áa]metros agron[óo]micos relevantes para «[^»]+»:\s*/i, '');
  t = t.replace(/^Contexto edafol[oó]gico general[^.]{0,150}\.\s*/i, '');
  t = t.replace(/\bconsulta\s*[:=]\s*[^.]+\./gi, '');
  const sentences = t.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(s => s.length > 10);
  const result = sentences.slice(0, 2).join(' ');
  return result.length > 300 ? result.slice(0, 297) + '...' : result;
}

// --- Estado legible del cultivo ---
function cropStatusLine(crop) {
  if (!crop) return '';
  const parts = [];
  if (crop.variety) parts.push(`variedad ${crop.variety}`);
  if (crop.growth_stage) parts.push(`etapa ${crop.growth_stage}`);
  if (crop.progress != null) parts.push(`avance ${crop.progress}%`);
  return parts.join(', ');
}

function buildCropStatusBlock(crop) {
  const label = cropDisplayLabel(crop);
  const meta = cropStatusLine(crop);
  const sensors = [];
  if (crop.soil_moisture != null) sensors.push(`humedad suelo ${Number(crop.soil_moisture).toFixed(0)}%`);
  if (crop.air_temp != null) sensors.push(`${Number(crop.air_temp).toFixed(0)}°C`);
  if (crop.air_humidity != null) sensors.push(`HR ${Number(crop.air_humidity).toFixed(0)}%`);
  let block = `${label}: ${meta}.`;
  if (sensors.length) block += ` Sensores: ${sensors.join(', ')}.`;
  return block;
}

// --- Riesgos simples ---
function evaluateRiskSimple(crop) {
  const risks = [];
  const soil = crop.soil_moisture;
  const temp = crop.air_temp;
  if (soil != null) {
    const profile = getCropProfileFor(crop);
    const max = profile?.soil_moisture_max || 75;
    const min = profile?.soil_moisture_min || 35;
    if (soil > max) risks.push(`humedad alta (${soil}% > ${max}%)`);
    else if (soil < min) risks.push(`humedad baja (${soil}% < ${min}%)`);
  }
  if (temp != null && temp > 34) risks.push(`temperatura elevada (${temp}°C)`);
  return risks;
}

// --- Acciones para un solo cultivo (TU FUNCIÓN ORIGINAL INTACTA) ---
function buildSimpleCropOnlyResponse(crop, risks) {
  const profile = getCropProfileFor(crop);
  const range = profile ? `${profile.soil_moisture_min || '?'}-${profile.soil_moisture_max || '?'}%` : 'sin perfil';
  const sm = crop.soil_moisture != null ? Number(crop.soil_moisture) : null;
  const lines = [];
  lines.push(buildCropStatusBlock(crop));
  if (sm != null && sm > (profile?.soil_moisture_max || 70)) {
    lines.push(`\nAcciones prioritarias:\n1. Suspender riego hasta que la humedad baje del ${range}.\n2. Revisar drenaje y encharcamientos.\n3. Evitar aplicaciones foliares que mantengan humedad alta.`);
  } else if (sm != null && sm < (profile?.soil_moisture_min || 35)) {
    lines.push(`\nAcciones prioritarias:\n1. Programar riego de recuperación (preferiblemente nocturno).\n2. Verificar humedad 4-6 horas después del riego.\n3. Ajustar frecuencia hasta alcanzar el rango ${range}.`);
  } else {
    lines.push(`\nAcciones prioritarias:\n1. Mantener el plan de riego actual.\n2. Recorrer el lote para detectar plagas o síntomas.\n3. Registrar lecturas en el próximo monitoreo.`);
  }
  if (risks.length) {
    lines.push(`\nAtención: ${risks.join('; ')}.`);
  }
  return lines.join('\n');
}

// --- Respuesta multi‑cultivo (agua) ---
function buildWaterMultiCropResponse(crops, globalReading) {
  const lines = [];
  lines.push(`Estado hídrico de tus ${crops.length} cultivos:`);
  for (const crop of crops) {
    const label = cropDisplayLabel(crop);
    const soil = crop.soil_moisture != null ? Number(crop.soil_moisture).toFixed(0) : '?';
    const profile = getCropProfileFor(crop);
    const range = profile ? `${profile.soil_moisture_min || '?'}-${profile.soil_moisture_max || '?'}%` : 'sin perfil';
    const status = soil !== '?' ? (soil < (profile?.soil_moisture_min || 35) ? 'baja' : soil > (profile?.soil_moisture_max || 75) ? 'alta' : 'adecuada') : 'sin datos';
    lines.push(`- ${label}: humedad suelo ${soil}% (rango óptimo ${range}) → estado ${status}.`);
  }
  if (globalReading?.precipitation != null) {
    lines.push(`\nPrecipitación reciente: ${Number(globalReading.precipitation).toFixed(1)} mm.`);
  }
  lines.push('\nRecomendación: revisa cada cultivo individualmente si necesitas acciones concretas.');
  return lines.join('\n');
}

// --- Respuesta general sin cultivo explícito ---
function buildGeneralStatusResponse(crops) {
  if (!crops.length) return 'Aún no tienes cultivos registrados. Puedes agregarlos en Configuración.';
  const list = crops.map(c => `- ${buildCropStatusBlock(c)}`).join('\n');
  return `Tus cultivos activos:\n${list}\n\n¿Sobre cuál te gustaría consultar?`;
}

// --- Construcción de respuesta principal ---
function buildStructuredResponse({
  context, message, ragPayloadJson, recommendation, ragConflict, requested, resolvedCrop,
}) {
  const activeCrops = (context.crops || []).filter(c => c.status !== 'inactivo');
  const requestedCrop = resolvedCrop;

  // Caso 0: conflicto (cultivo no activo)
  if (ragConflict && requested) {
    const label = requested.charAt(0).toUpperCase() + requested.slice(1);
    const cleaned = extractRagAnswer(ragPayloadJson);
    return `Aviso: preguntaste por "${label}" pero no es un cultivo activo en tu parcela. Información de la biblioteca:\n${cleaned || 'Sin información específica.'}`;
  }

  // Caso 1: sin cultivos
  if (!activeCrops.length) {
    const cleaned = extractRagAnswer(ragPayloadJson);
    return cleaned || 'No tienes cultivos registrados. Agrega uno en Configuración para recibir recomendaciones personalizadas.';
  }

  const isWater = isWaterBalanceQuery(message);
  
  // Caso 2: agua/humedad sin cultivo explícito -> multi‑cultivo
  if (isWater && !requestedCrop && activeCrops.length > 1) {
    return buildWaterMultiCropResponse(activeCrops, context.globalReading);
  }

  // Caso 3: solo el nombre del cultivo (o intenciones como "acciones para maiz")
  if (requestedCrop && isOnlyCropNameQuery(message, requestedCrop)) {
    const risks = evaluateRiskSimple(requestedCrop);
    return buildSimpleCropOnlyResponse(requestedCrop, risks);
  }

  // Caso 4: pregunta sobre cosecha (extraer fecha)
  if (requestedCrop && isHarvestDateQuery(message)) {
    const estimated = requestedCrop.expected_harvest_at
      ? `Según tu registro, la cosecha estimada es el ${new Date(requestedCrop.expected_harvest_at).toLocaleDateString('es-MX')}.`
      : 'No tienes una fecha de cosecha estimada registrada.';
    const risks = evaluateRiskSimple(requestedCrop);
    const status = buildCropStatusBlock(requestedCrop);
    let extra = `${status}\n\n${estimated}`;
    if (risks.length) extra += `\nAtención: ${risks.join('; ')}.`;
    return extra;
  }

  // Caso 5: cultivo explícito con consulta RAG
  if (requestedCrop) {
    const cleaned = extractRagAnswer(ragPayloadJson);
    const status = buildCropStatusBlock(requestedCrop);
    const risks = evaluateRiskSimple(requestedCrop);
    let out = `${status}\n\n${cleaned || 'No encontré información específica confirmada para tu consulta.'}`;
    if (risks.length) out += `\n\nAtención: ${risks.join('; ')}.`;
    
    // Aquí conservamos la recomendación y el detail_html que tenías en tu código original
    if (recommendation?.action) {
      const det = cleanMotorDetail(recommendation.detail_html);
      out += `\n\nRecomendación del sistema: ${recommendation.action}.`;
      if (det) out += ` ${det}`;
    }
    return out;
  }

  // Caso 6: sin cultivo explícito (ej: "calor", "lluvia")
  const cleaned = extractRagAnswer(ragPayloadJson);
  if (cleaned) return cleaned;
  
  // Si la IA evaluó "insufficient_evidence", cae aquí en lugar de alucinar:
  return `No tengo información suficiente en la biblioteca para responder sobre eso.\n\n${buildGeneralStatusResponse(activeCrops)}`;
}

// --- Funciones de apoyo ---
function isOnlyCropNameQuery(message, crop) {
  const msg = normalizeCropName(message);
  if (!msg) return false;
  const variants = cropNameVariants(crop);
  
  // 1. Si escribió solo "maiz"
  if (variants.some(v => msg === v)) return true;
  
  // 2. NUEVO: Si escribió intención operativa (ej. "acciones para maiz", "recomendaciones maiz")
  const actionIntent = /\b(acci[oó]n|acciones|recomendaci[oó]n|recomendaciones|estado|resumen)\b/;
  return actionIntent.test(msg) && variants.some(v => msg.includes(v));
}

function isHarvestDateQuery(message) {
  const m = normalizeCropName(message);
  return /\b(cu[aá]ndo\s+(cosech|recolect)|fecha\s+de\s+cosech|pr[oó]xima\s+cosech|falta\s+para\s+cosech)\b/i.test(m);
}

// --- Resolver objetivos del chat ---
function resolveChatCropTargets(message, context) {
  const activeCrops = (context.crops || []).filter(c => c.status !== 'inactivo');
  const requested = detectRequestedCrop(message, activeCrops);
  const requestedCrop = requested ? matchRequestedToActiveCrop(requested, activeCrops) : null;
  const fallbackTarget = activeCrops[0] || null;
  const ragConflict = Boolean(requested && !requestedCrop);
  let ragPayload = { retrieval_scope: 'global' };
  let recoCrop = null;
  if (ragConflict) {
    ragPayload = { crop_focus: requested, retrieval_scope: 'crop_boost' };
  } else if (requestedCrop || fallbackTarget) {
    const t = requestedCrop || fallbackTarget;
    ragPayload = { crop_focus: t.crop_name, user_crop_id: Number(t.id), retrieval_scope: 'crop_boost' };
    recoCrop = t;
  }
  return { activeCrops, requested, requestedCrop, fallbackTarget, ragConflict, ragPayload, recoCrop };
}

// --- Función principal de AgroBot ---
async function responderComoBot(mensaje, usuarioId, usuarioNombre) {
  const BOT_ID = 0;
  const enqueue = (texto) => {
    setTimeout(() => {
      const botMsg = { usuarioId: String(BOT_ID), usuario: 'AgroBot', texto, fecha: new Date().toISOString() };
      io.to(`user:${usuarioId}`).emit('nuevo_mensaje', botMsg);
      stmts.insertMessage.run(null, usuarioId, 'AgroBot', texto, 'text');
    }, 600);
  };

  if (isLowConfidenceChatInput(mensaje)) {
    enqueue(chatGarbageReply());
    return;
  }
  if (shouldThrottleDuplicateChat(usuarioId, mensaje)) {
    enqueue('Recibí ese mismo texto hace unos segundos. Si querés otra cosa, reformulá la consulta.');
    return;
  }

  const context = buildChatQuery(mensaje, usuarioId);
  const { requested, requestedCrop, ragConflict, ragPayload, recoCrop } = resolveChatCropTargets(mensaje, context);
  const isWater = isWaterBalanceQuery(mensaje);

  // Construir consulta hacia el RAG
  let queryForRag = String(mensaje || '').trim();
  if (recoCrop && !isWater) {
    const statusLine = buildCropStatusBlock(recoCrop);
    queryForRag = `Eres un asistente agrícola experto. Cultivo: ${recoCrop.crop_name} (${statusLine}). Pregunta del agricultor: "${mensaje}". Responde de forma práctica y breve, sin historia ni orígenes.`;
  } else if (!recoCrop && !isWater) {
    const list = (context.crops || []).filter(c => c.status !== 'inactivo').map(c => cropDisplayLabel(c)).join(', ');
    queryForRag = `Responde de forma concisa a esta consulta: "${mensaje}". El usuario tiene estos cultivos: ${list}. Evita historia u orígenes.`;
  }

  let ragPayloadJson;
  try {
    const resp = await fetch(`${AI_BACKEND}/api/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: queryForRag, k: 8, mode: 'hybrid', ...ragPayload }),
    });
    if (!resp.ok) throw new Error(`Backend respondió ${resp.status}`);
    ragPayloadJson = await resp.json();
  } catch (err) {
    enqueue(`Error al consultar la biblioteca: ${err.message}`);
    return;
  }

  let recommendation = null;
  if (recoCrop?.id && !isWater) {
    try {
      const recResp = await fetch(`${AI_BACKEND}/api/recommendations/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_crop_id: Number(recoCrop.id) }),
      });
      if (recResp.ok) recommendation = await recResp.json();
    } catch (_) {}
  }

  const respuesta = buildStructuredResponse({
    context, message: mensaje, ragPayloadJson: ragPayloadJson, recommendation,
    ragConflict, requested, resolvedCrop: recoCrop,
  });

  enqueue(respuesta);
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