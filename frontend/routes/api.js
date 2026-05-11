// routes/api.js — Autenticación, perfil, ajustes, calendario, uploads y proxy al backend IA.
const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const router = express.Router();

// --- Config ---
const JWT_SECRET = process.env.JWT_SECRET || '12345';
const JWT_EXPIRES_IN = '24h';
const SQLITE_PATH = path.resolve(__dirname, '..', process.env.SQLITE_PATH || '../milpa_ai_backend/data/milpa_knowledge.db');
const AI_BACKEND = process.env.AI_BACKEND_URL || 'http://127.0.0.1:8000';
const UPLOADS_ROOT = path.resolve(__dirname, '..', 'MILPA', 'uploads');

// --- DB connection ---
const db = new Database(SQLITE_PATH);
db.pragma('journal_mode = WAL');

db.exec(`
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
    source_kind TEXT NOT NULL DEFAULT 'usuario' CHECK(source_kind IN ('usuario', 'ia')),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (user_crop_id) REFERENCES user_crops(id)
  );

  CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON calendar_events(user_id);
  CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_date);
`);

// Ajustes defensivos de esquema (instalaciones previas sin columnas nuevas)
try {
  const calendarCols = db.prepare('PRAGMA table_info(calendar_events)').all();
  if (!calendarCols.some(col => col.name === 'source_kind')) {
    db.exec("ALTER TABLE calendar_events ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'usuario'");
  }
} catch (error) {
  console.warn('No se pudo ajustar schema de calendar_events:', error.message);
}

fs.mkdirSync(path.join(UPLOADS_ROOT, 'avatars'), { recursive: true });
fs.mkdirSync(path.join(UPLOADS_ROOT, 'crops'), { recursive: true });

/** FAQs por defecto + reglas tomate si la BD es antigua */
function ensureContentSeeds() {
  try {
    db.exec(`
      CREATE TABLE IF NOT EXISTS faqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        crop_name TEXT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        related_doc_id TEXT,
        priority INTEGER DEFAULT 100,
        created_at TEXT DEFAULT (datetime('now'))
      );
      CREATE INDEX IF NOT EXISTS idx_faqs_category ON faqs(category);
      CREATE INDEX IF NOT EXISTS idx_faqs_crop ON faqs(crop_name);
    `);
    const cnt = db.prepare('SELECT COUNT(*) AS c FROM faqs').get();
    if (!cnt || cnt.c === 0) {
      const ins = db.prepare(`
        INSERT OR IGNORE INTO faqs (id, category, crop_name, question, answer, priority) VALUES (?, ?, ?, ?, ?, ?)
      `);
      [
        [1, 'siembra', 'maiz', '¿Cuál es el mejor momento para sembrar maíz?', 'Siembra cuando el suelo alcanza al menos 18 °C de forma estable y la humedad esté entre 45 % y 75 %. En milpa tradicional suele alinearse con el inicio de lluvias.', 10],
        [2, 'plagas', null, '¿Cómo controlar plagas sin químicos?', 'Rota cultivos, trampas cromáticas, enemigos naturales y biocontrol; actúa si superas umbral de daño económico.', 20],
        [3, 'sistema', null, '¿Qué beneficios tiene la milpa?', 'Fijación de N, cobertura del suelo, dieta diversa y menor dependencia de insumos frente al monocultivo.', 30],
        [4, 'monitoreo', null, '¿Qué revisar en cada visita?', 'Humedad de suelo, temperatura, plagas y fenología. MILPA cruza umbrales con tu perfil y sensores.', 70],
      ].forEach(r => ins.run(...r));
    }
    try {
      db.exec(`
        INSERT OR IGNORE INTO crop_calendar_rules
          (crop_name, event_type_slug, day_offset, title_template, description_template, trigger_condition, rationale, source_doc_hint, priority)
        VALUES
          ('tomate', 'sowing', 0, 'Trasplante / inicio de {crop_display}', 'Verificar riego de establecimiento y protección contra heladas tardías.', 'always', 'Inicio de ciclo.', 'manual_operativo_milpa_2026', 10),
          ('tomate', 'monitoring', 7, 'Monitoreo temprano de {crop_display}', 'Entallado, tutorado, humedad; plagas foliares.', 'always', 'Tomate requiere seguimiento frecuente.', 18),
          ('tomate', 'irrigation', 10, 'Riego de sostén — {crop_display}', 'Evitar encharcar; alternancia seca/húmeda moderada.', 'soil_moisture_low', 'Prevención de fisuras en fruto.', 25),
          ('tomate', 'fertilization', 21, 'Nutrición vegetativo-floración — {crop_display}', 'NPK según suelo y etapa; prefertilización si hay déficit.', 'always', 'Soporte a floración y cuaje.', 32),
          ('tomate', 'pest', 28, 'Inspección plagas — {crop_display}', 'Tuta absoluta, trips, trips polífagos; trampas si aplica.', 'always', 'Detección temprana reduce pérdidas.', 20),
          ('tomate', 'harvest', 100, 'Ventana de cosecha — {crop_display}', 'Color, firmeza y °Brix; ajustar por variedad.', 'always', 'Referencia orientativa de ciclo.', 14);
      `);
    } catch (ruleErr) {
      console.warn('Reglas tomate (crop_calendar_rules):', ruleErr.message);
    }
  } catch (e) {
    console.warn('ensureContentSeeds:', e.message);
  }
}

ensureContentSeeds();

// El ciclo típico del cultivo (días) se lee desde `crop_profiles.cycle_days`
// (migración 0013). NO hay condicionales por cultivo en código: cualquier
// cultivo nuevo se respeta vía INSERT/UPDATE sobre crop_profiles.
//
// Caché de cultivos conocidos (in-memory) refrescado cuando cambia la BD;
// se invalida automáticamente al detectar nuevas filas.
let _knownCropsCache = null;
let _knownCropsCacheAt = 0;
const TYPICAL_CYCLE_DEFAULT = 115;

function loadKnownCrops() {
  // Máx 30s de caché para amortiguar carga, pero suficientemente fresco
  // para reflejar agregar/quitar cultivos en `crop_profiles`.
  const now = Date.now();
  if (_knownCropsCache && now - _knownCropsCacheAt < 30000) {
    return _knownCropsCache;
  }
  try {
    let rows;
    try {
      rows = db.prepare('SELECT LOWER(crop_name) AS crop_name, variety, cycle_days FROM crop_profiles').all();
    } catch (_e) {
      // Migración 0013 todavía no aplicada: leer sin cycle_days.
      rows = db.prepare('SELECT LOWER(crop_name) AS crop_name, variety FROM crop_profiles').all().map(r => ({ ...r, cycle_days: null }));
    }
    _knownCropsCache = rows;
    _knownCropsCacheAt = now;
    return rows;
  } catch (_e) {
    _knownCropsCache = [];
    _knownCropsCacheAt = now;
    return [];
  }
}

function typicalCycleDays(cropName) {
  const target = String(cropName || '').trim().toLowerCase();
  if (!target) return TYPICAL_CYCLE_DEFAULT;
  const rows = loadKnownCrops();
  // Match exacto primero, luego LIKE/contains (cubre 'maíz' vs 'maiz', 'jitomate' vs 'tomate').
  const exact = rows.find(r => r.crop_name === target);
  if (exact && exact.cycle_days != null) return Math.max(15, Number(exact.cycle_days));
  const partial = rows.find(r => r.crop_name && (r.crop_name.includes(target) || target.includes(r.crop_name)));
  if (partial && partial.cycle_days != null) return Math.max(15, Number(partial.cycle_days));
  return TYPICAL_CYCLE_DEFAULT;
}

function knownCropNames() {
  return loadKnownCrops().map(r => r.crop_name).filter(Boolean);
}

function daysBetweenIso(startIso, endIso) {
  const a = new Date(startIso);
  const b = new Date(endIso);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
  return Math.floor((b - a) / 86400000);
}

function computeAgronomicHealth(crop, latest, settings) {
  const s = settings || {};
  const minSoil = Number(s.min_soil_moisture ?? 40);
  const maxTemp = Number(s.max_temperature ?? 35);
  const minHum = Number(s.min_air_humidity ?? 50);

  const factors = [];
  let score = 100;

  const planted = crop.planted_at ? String(crop.planted_at).slice(0, 10) : null;
  const today = new Date().toISOString().slice(0, 10);
  const daysPlanted = planted ? daysBetweenIso(planted, today) : null;

  if (!latest || (latest.soil_moisture == null && latest.air_temp == null)) {
    factors.push({ code: 'sin_telemetria', severity: 'info', message: 'Sin lecturas recientes de sensor para este cultivo.' });
    score -= 15;
  }

  const soil = latest?.soil_moisture != null ? Number(latest.soil_moisture) : null;
  if (soil != null) {
    if (soil < minSoil - 12) {
      score -= 38;
      factors.push({ code: 'agua_critica', severity: 'high', message: `Humedad de suelo muy baja (${soil.toFixed(0)} %; objetivo mínimo ~${minSoil} %).` });
    } else if (soil < minSoil) {
      score -= 18;
      factors.push({ code: 'agua_baja', severity: 'medium', message: `Humedad de suelo por debajo del umbral (${soil.toFixed(0)} %).` });
    }
  }

  const temp = latest?.air_temp != null ? Number(latest.air_temp) : null;
  if (temp != null) {
    if (temp >= maxTemp + 4) {
      score -= 35;
      factors.push({ code: 'calor_extremo', severity: 'high', message: `Temperatura muy alta (${temp.toFixed(0)} °C); riesgo de estrés térmico.` });
    } else if (temp > maxTemp) {
      score -= 15;
      factors.push({ code: 'calor', severity: 'medium', message: `Temperatura elevada (${temp.toFixed(0)} °C).` });
    }
  }

  const hum = latest?.air_humidity != null ? Number(latest.air_humidity) : null;
  if (hum != null && hum < minHum - 15) {
    score -= 12;
    factors.push({ code: 'aire_seco', severity: 'low', message: `Humedad relativa baja (${hum.toFixed(0)} %).` });
  }

  const cycle = typicalCycleDays(crop.crop_name);
  if (daysPlanted != null && daysPlanted >= 0 && cycle > 0) {
    const expectedProgress = Math.min(100, Math.round((daysPlanted / cycle) * 100));
    const reported = Number(crop.progress ?? 0);
    const lag = reported - expectedProgress;
    if (lag < -35) {
      score -= 28;
      factors.push({
        code: 'fenologia_atrasada',
        severity: 'high',
        message: `Avance reportado (${reported} %) muy por debajo del esperado para día ${daysPlanted} del ciclo (~${expectedProgress} %).`,
      });
    } else if (lag < -18) {
      score -= 14;
      factors.push({
        code: 'fenologia_rezaga',
        severity: 'medium',
        message: 'Posible rezago fenológico respecto al tiempo desde siembra.',
      });
    }
  }

  score = Math.max(0, Math.min(100, Math.round(score)));

  let label = 'Saludable';
  const severe = factors.some(f => f.severity === 'high');

  if (daysPlanted != null && daysPlanted < 21 && !severe) {
    label = 'Establecimiento';
  } else if (score >= 72 && !severe) {
    label = 'Saludable';
  } else if (score >= 48) {
    label = 'Vigilancia';
  } else if (score >= 28) {
    label = 'Crítico';
  } else {
    label = severe ? 'Crítico' : 'Establecimiento';
  }

  const summary = factors.length
    ? factors.map(f => f.message).join(' ')
    : 'Condiciones dentro de rangos configurados y ritmo coherente con el ciclo.';

  return {
    label,
    score,
    factors,
    summary,
    expected_progress_hint: daysPlanted != null ? Math.min(100, Math.round((daysPlanted / typicalCycleDays(crop.crop_name)) * 100)) : null,
    days_since_planting: daysPlanted,
  };
}

function suggestRollingMonitoringEvents(userId, horizonDays = 21) {
  const inserted = [];
  const today = new Date().toISOString().slice(0, 10);
  const horizonEnd = addDaysIso(today, horizonDays);
  const crops = db.prepare(`
    SELECT * FROM user_crops WHERE user_id = ? AND status = 'activo'
  `).all(userId);

  const tx = db.transaction(() => {
    for (const c of crops) {
      for (const offsetDays of [0, 7, 14]) {
        const d = addDaysIso(today, offsetDays);
        if (!d || d > horizonEnd) continue;
        const title = `Visita de campo — ${c.display_name || c.crop_name}`;
        const exists = db.prepare(`
          SELECT id FROM calendar_events
          WHERE user_id = ? AND user_crop_id = ? AND start_date = ? AND title = ?
        `).get(userId, c.id, d, title);
        if (exists) continue;

        const plantedNote = c.planted_at
          ? ` Días desde siembra: ${daysBetweenIso(String(c.planted_at).slice(0, 10), today) ?? 'N/D'}.`
          : '';
        const desc = [
          `Sugerencia MILPA (IA operativa): revisar malezas, humedad de suelo, plagas y fenología (${c.growth_stage || 'sin etapa'}).`,
          plantedNote,
          'Priorizar según alertas y recomendaciones del sistema.',
        ].join('');

        const result = db.prepare(`
          INSERT INTO calendar_events
            (user_id, user_crop_id, title, event_type, start_date, end_date, description, status, source_kind)
          VALUES (?, ?, ?, 'monitoring', ?, ?, ?, 'programado', 'ia')
        `).run(userId, c.id, title, d, d, desc);

        inserted.push({
          id: Number(result.lastInsertRowid),
          user_crop_id: c.id,
          event_date: d,
          title,
          source_kind: 'ia',
          kind: 'rolling_monitoring',
        });
      }
    }
  });
  tx();
  return { inserted, basis: 'Visitas sugeridas según cultivos activos y ventana próxima (no sustituye reglas por día desde siembra).' };
}

const PROFILE_FIELDS = ['first_name', 'last_name', 'bio', 'location', 'experience', 'lat', 'lon', 'geo_zoom'];
const ACCOUNT_FIELDS = ['email', 'phone', 'language'];
const SETTINGS_FIELDS = [
  'email_alerts', 'daily_summary', 'weekly_report', 'push_alerts', 'push_recommendations',
  'push_reminders', 'notification_frequency', 'min_soil_moisture', 'max_temperature',
  'min_air_humidity', 'pest_threshold', 'alert_water', 'alert_temp', 'alert_pests',
  'alert_growth', 'alert_weather', 'data_collection', 'research_participation', 'location_sharing'
];
const BOOLEAN_SETTINGS = new Set([
  'email_alerts', 'daily_summary', 'weekly_report', 'push_alerts', 'push_recommendations',
  'push_reminders', 'alert_water', 'alert_temp', 'alert_pests', 'alert_growth',
  'alert_weather', 'data_collection', 'research_participation', 'location_sharing'
]);

// Prepared statements
const stmts = {
  findUserByUsername: db.prepare('SELECT * FROM users WHERE username = ?'),
  insertUser: db.prepare('INSERT INTO users (username, password_hash) VALUES (?, ?)'),
  getUserById: db.prepare('SELECT id, username, password_hash, created_at FROM users WHERE id = ?'),
  getUserWithProfile: db.prepare(`
    SELECT
      u.id,
      u.username,
      p.first_name,
      p.last_name,
      p.bio,
      p.location,
      p.experience,
      p.avatar_path,
      p.email,
      p.phone,
      COALESCE(p.language, 'Español') AS language,
      p.lat,
      p.lon,
      p.geo_zoom,
      u.created_at
    FROM users u
    LEFT JOIN user_profiles p ON p.user_id = u.id
    WHERE u.id = ?
  `),
  getUserSettings: db.prepare('SELECT * FROM user_settings WHERE user_id = ?'),
  getCalendarEvents: db.prepare(`
    SELECT
      e.id,
      e.user_id,
      e.user_crop_id,
      e.title,
      e.event_type,
      e.start_date,
      e.end_date,
      e.description,
      e.status,
      e.source_kind,
      e.created_at,
      e.updated_at,
      c.crop_name
    FROM calendar_events e
    LEFT JOIN user_crops c ON c.id = e.user_crop_id
    WHERE e.user_id = ?
    ORDER BY e.start_date ASC, e.created_at ASC
  `),
  insertDefaultProfile: db.prepare('INSERT OR IGNORE INTO user_profiles (user_id, first_name) VALUES (?, ?)'),
  insertDefaultSettings: db.prepare('INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)'),
};

function ensureUserSupportRows(userId) {
  const user = stmts.getUserById.get(userId);
  if (!user) {
    return null;
  }
  stmts.insertDefaultProfile.run(userId, user.username);
  stmts.insertDefaultSettings.run(userId);
  return user;
}

function sanitizeFileStem(value) {
  return String(value || 'archivo')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase() || 'archivo';
}

function safeBooleanInt(value) {
  return value ? 1 : 0;
}

function pickFields(source, allowedFields, transform = null) {
  const picked = {};
  for (const field of allowedFields) {
    if (Object.prototype.hasOwnProperty.call(source, field) && source[field] !== undefined) {
      picked[field] = transform ? transform(field, source[field]) : source[field];
    }
  }
  return picked;
}

function updateRow(tableName, keyField, keyValue, values) {
  const entries = Object.entries(values).filter(([, value]) => value !== undefined);
  if (!entries.length) {
    return false;
  }
  const assignments = entries.map(([field]) => `${field} = ?`);
  const params = entries.map(([, value]) => value);
  params.push(keyValue);
  db.prepare(`UPDATE ${tableName} SET ${assignments.join(', ')}, updated_at = datetime('now') WHERE ${keyField} = ?`).run(...params);
  return true;
}

function removeManagedUpload(relativePath) {
  if (!relativePath || typeof relativePath !== 'string') {
    return;
  }
  const normalized = relativePath.replace(/^\/+/, '').replace(/\\/g, '/');
  if (!normalized.startsWith('uploads/')) {
    return;
  }
  const absolutePath = path.resolve(path.join(__dirname, '..', 'MILPA', normalized));
  const uploadsBase = path.resolve(path.join(__dirname, '..', 'MILPA', 'uploads'));
  if (!absolutePath.startsWith(uploadsBase)) {
    return;
  }
  if (fs.existsSync(absolutePath)) {
    fs.unlinkSync(absolutePath);
  }
}

function saveImageData(imageData, folder, stem) {
  if (typeof imageData !== 'string') {
    throw new Error('Imagen inválida.');
  }
  const match = imageData.match(/^data:(image\/(png|jpeg|jpg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$/i);
  if (!match) {
    throw new Error('Formato de imagen no soportado.');
  }
  const mimeType = match[1].toLowerCase();
  const rawBase64 = match[3].replace(/\s+/g, '');
  const buffer = Buffer.from(rawBase64, 'base64');
  if (!buffer.length) {
    throw new Error('La imagen está vacía.');
  }
  if (buffer.length > 5 * 1024 * 1024) {
    throw new Error('La imagen excede el límite de 5 MB.');
  }

  const extensionMap = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/webp': 'webp',
    'image/gif': 'gif',
  };
  const extension = extensionMap[mimeType];
  if (!extension) {
    throw new Error('Extensión de imagen no soportada.');
  }

  const fileName = `${sanitizeFileStem(stem)}-${Date.now()}-${crypto.randomBytes(4).toString('hex')}.${extension}`;
  const absolutePath = path.join(UPLOADS_ROOT, folder, fileName);
  fs.writeFileSync(absolutePath, buffer);
  return `uploads/${folder}/${fileName}`;
}

async function proxyToBackend(req, res, targetPath) {
  const url = `${AI_BACKEND}${targetPath}`;
  try {
    const headers = {};
    if (req.headers['content-type'] && ['POST', 'PUT', 'PATCH'].includes(req.method)) {
      headers['Content-Type'] = req.headers['content-type'];
    }
    const options = {
      method: req.method,
      headers,
    };
    if (['POST', 'PUT', 'PATCH'].includes(req.method) && req.body && Object.keys(req.body).length) {
      options.body = JSON.stringify(req.body);
      if (!options.headers['Content-Type']) {
        options.headers['Content-Type'] = 'application/json';
      }
    }
    const response = await fetch(url, options);
    const data = await response.text();
    const contentType = response.headers.get('content-type');
    res.status(response.status);
    if (contentType) {
      res.set('Content-Type', contentType);
    }
    res.send(data);
  } catch (err) {
    console.error('Proxy backend error:', err.message);
    res.status(502).json({ error: 'No se pudo conectar con el backend.' });
  }
}

async function generateAutoRecommendationsForUser(userId) {
  const crops = db.prepare(`
    SELECT id
    FROM user_crops
    WHERE user_id = ? AND status = 'activo'
    ORDER BY created_at DESC
  `).all(userId);
  const created = [];
  const skipped = [];
  for (const crop of crops) {
    try {
      const response = await fetch(`${AI_BACKEND}/api/recommendations/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_crop_id: Number(crop.id) }),
      });
      if (!response.ok) {
        skipped.push({ crop_id: crop.id, reason: `backend_${response.status}` });
        continue;
      }
      const rec = await response.json();
      created.push(rec);
    } catch (error) {
      skipped.push({ crop_id: crop.id, reason: error.message || 'network_error' });
    }
  }
  return { created, skipped };
}

function normalizeNumeric(value, fallback = null) {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function normalizeText(value, fallback = null) {
  if (value === null || value === undefined) {
    return fallback;
  }
  const text = String(value).trim();
  return text.length ? text : fallback;
}

function normalizeIsoDate(value, fallback = null) {
  const text = normalizeText(value, null);
  if (!text) {
    return fallback;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return fallback;
  }
  if (text.length <= 10) {
    return text;
  }
  return parsed.toISOString().slice(0, 19).replace('T', ' ');
}

function addDaysIso(baseDate, daysOffset) {
  const base = new Date(baseDate);
  if (Number.isNaN(base.getTime())) {
    return null;
  }
  base.setDate(base.getDate() + Number(daysOffset || 0));
  return base.toISOString().slice(0, 10);
}

function fillRuleTemplate(template, crop) {
  const display = crop.display_name || crop.crop_name || 'cultivo';
  return String(template || '')
    .replaceAll('{crop_display}', display)
    .replaceAll('{crop_name}', crop.crop_name || 'cultivo');
}

function parseDatasetPayload(input) {
  if (!input) {
    throw new Error('Debes enviar el dataset en el campo dataset.');
  }
  if (typeof input === 'string') {
    try {
      return JSON.parse(input);
    } catch {
      throw new Error('El JSON del dataset no es valido.');
    }
  }
  if (typeof input === 'object') {
    return input;
  }
  throw new Error('Formato de dataset no soportado.');
}

function buildCropDefaults(cropName, index) {
  const normalized = String(cropName || 'cultivo').trim().toLowerCase();
  const displayBase = normalized ? `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}` : `Cultivo ${index + 1}`;
  const plantedAt = new Date(Date.now() - (index + 4) * 86400000 * 7);
  return {
    crop_name: normalized || `cultivo_${index + 1}`,
    display_name: `${displayBase} lote ${index + 1}`,
    status: 'activo',
    growth_stage: 'desarrollo',
    progress: 45,
    planted_at: plantedAt.toISOString().slice(0, 10),
  };
}

function generateMonitoringDatasetTemplate(weeks = 24, intervalDays = 7) {
  const cropNames = ['maiz', 'frijol', 'chile'];
  const crops = cropNames.map((name, index) => ({
    ...buildCropDefaults(name, index),
    variety: index === 0 ? 'Criollo' : index === 1 ? 'Negro' : 'Serrano',
  }));

  const sensor_readings = [];
  const global_readings = [];
  const now = new Date();

  for (let week = 0; week < weeks; week += 1) {
    const ts = new Date(now.getTime() - (weeks - 1 - week) * intervalDays * 86400000);
    ts.setHours(12, 0, 0, 0);
    const createdAt = ts.toISOString().slice(0, 19).replace('T', ' ');

    cropNames.forEach((cropName, cropIndex) => {
      const seed = week + cropIndex * 3;
      const soil = 44 + (seed % 8) * 3;
      const airTemp = 19 + (seed % 9) * 1.7;
      const humidity = 42 + (seed % 10) * 3.1;
      const light = 58 + (seed % 9) * 3.2;
      const precipitation = seed % 5 === 0 ? 6.8 : 0.0;
      const windSpeed = 5.5 + (seed % 6) * 0.8;
      sensor_readings.push({
        crop_name: cropName,
        soil_moisture: Number(soil.toFixed(1)),
        air_temp: Number(airTemp.toFixed(1)),
        air_humidity: Number(humidity.toFixed(1)),
        light: Number(light.toFixed(1)),
        precipitation: Number(precipitation.toFixed(1)),
        wind_speed: Number(windSpeed.toFixed(1)),
        created_at: createdAt,
      });
    });

    global_readings.push({
      location_name: 'general',
      soil_temp: Number((18 + (week % 8) * 1.1).toFixed(1)),
      air_temp: Number((20 + (week % 10) * 1.4).toFixed(1)),
      air_humidity: Number((45 + (week % 9) * 2.8).toFixed(1)),
      soil_moisture: Number((40 + (week % 10) * 2.9).toFixed(1)),
      precipitation: Number((week % 4 === 0 ? 8.2 : 0.0).toFixed(1)),
      wind_speed: Number((6 + (week % 6) * 0.7).toFixed(1)),
      ph: Number((6.2 + (week % 5) * 0.1).toFixed(2)),
      conductivity: Number((0.9 + (week % 4) * 0.15).toFixed(2)),
      notes: 'Lectura global periodica importada desde dataset.',
      created_at: createdAt,
    });
  }

  return {
    metadata: {
      format_version: '1.0',
      description: 'Dataset de monitoreo semanal por usuario',
      generated_at: new Date().toISOString(),
      interval_days: intervalDays,
      weeks,
    },
    crops,
    sensor_readings,
    global_readings,
  };
}

function importDatasetForUser(userId, dataset, options = {}) {
  const clearExisting = Boolean(options.clearExisting);
  const cropRows = Array.isArray(dataset?.crops) ? dataset.crops : [];
  const sensorRows = Array.isArray(dataset?.sensor_readings) ? dataset.sensor_readings : [];
  const globalRows = Array.isArray(dataset?.global_readings) ? dataset.global_readings : [];
  const nutrientRows = Array.isArray(dataset?.soil_nutrients) ? dataset.soil_nutrients : [];
  const irrigationRows = Array.isArray(dataset?.irrigation_events) ? dataset.irrigation_events : [];

  if (!cropRows.length && !sensorRows.length && !globalRows.length && !nutrientRows.length && !irrigationRows.length) {
    throw new Error('El dataset no contiene bloques importables (crops, sensor_readings, global_readings, soil_nutrients o irrigation_events).');
  }

  const summary = {
    created_crops: 0,
    inserted_sensor_readings: 0,
    inserted_global_readings: 0,
    inserted_soil_nutrients: 0,
    skipped_sensor_readings: 0,
    cleared_existing: clearExisting,
  };

  const cropNameToId = new Map();
  const cropIndexToId = new Map();

  const tx = db.transaction(() => {
    if (clearExisting) {
      const cropIds = db.prepare('SELECT id FROM user_crops WHERE user_id = ?').all(userId).map(row => row.id);
      if (cropIds.length) {
        const placeholders = cropIds.map(() => '?').join(', ');
        db.prepare(`DELETE FROM sensor_readings WHERE user_crop_id IN (${placeholders})`).run(...cropIds);
        db.prepare(`DELETE FROM recommendations WHERE user_crop_id IN (${placeholders})`).run(...cropIds);
        db.prepare(`DELETE FROM calendar_events WHERE user_crop_id IN (${placeholders})`).run(...cropIds);
      }
      db.prepare('DELETE FROM user_crops WHERE user_id = ?').run(userId);
    }

    const userCropRows = db.prepare('SELECT id, crop_name FROM user_crops WHERE user_id = ?').all(userId);
    for (const row of userCropRows) {
      if (row.crop_name) {
        cropNameToId.set(String(row.crop_name).toLowerCase(), row.id);
      }
    }

    const insertCropStmt = db.prepare(
      'INSERT INTO user_crops (user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, growth_stage, image_path, status, progress, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    );

    cropRows.forEach((rawCrop, index) => {
      const defaults = buildCropDefaults(rawCrop?.crop_name, index);
      const cropName = normalizeText(rawCrop?.crop_name, defaults.crop_name).toLowerCase();
      const displayName = normalizeText(rawCrop?.display_name, defaults.display_name);
      const variety = normalizeText(rawCrop?.variety, null);
      const plantedAt = normalizeIsoDate(rawCrop?.planted_at, defaults.planted_at);
      const expectedHarvestAt = normalizeIsoDate(rawCrop?.expected_harvest_at, null);
      const growthStage = normalizeText(rawCrop?.growth_stage, defaults.growth_stage);
      const imagePath = normalizeText(rawCrop?.image_path, null);
      const status = normalizeText(rawCrop?.status, defaults.status);
      const progress = normalizeNumeric(rawCrop?.progress, defaults.progress);
      const notes = normalizeText(rawCrop?.notes, null);

      const existingId = cropNameToId.get(cropName);
      if (existingId) {
        db.prepare(
          'UPDATE user_crops SET display_name = ?, variety = ?, planted_at = ?, expected_harvest_at = ?, growth_stage = ?, image_path = ?, status = ?, progress = ?, notes = ? WHERE id = ?'
        ).run(displayName, variety, plantedAt, expectedHarvestAt, growthStage, imagePath, status, progress, notes, existingId);
        cropIndexToId.set(index, existingId);
        return;
      }

      const result = insertCropStmt.run(
        userId,
        cropName,
        displayName,
        variety,
        plantedAt,
        expectedHarvestAt,
        growthStage,
        imagePath,
        status,
        progress,
        notes,
      );

      const newCropId = Number(result.lastInsertRowid);
      cropNameToId.set(cropName, newCropId);
      cropIndexToId.set(index, newCropId);
      summary.created_crops += 1;
    });

    const insertSensorStmt = db.prepare(
      'INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    );

    sensorRows.forEach(rawReading => {
      let targetCropId = null;

      const explicitCropId = normalizeNumeric(rawReading?.user_crop_id, null);
      if (explicitCropId) {
        const crop = db.prepare('SELECT id FROM user_crops WHERE id = ? AND user_id = ?').get(explicitCropId, userId);
        if (crop) {
          targetCropId = crop.id;
        }
      }

      if (!targetCropId) {
        const cropIndex = normalizeNumeric(rawReading?.crop_index, null);
        if (cropIndex !== null && cropIndexToId.has(cropIndex)) {
          targetCropId = cropIndexToId.get(cropIndex);
        }
      }

      if (!targetCropId) {
        const cropNameKey = normalizeText(rawReading?.crop_name, '').toLowerCase();
        if (cropNameKey && cropNameToId.has(cropNameKey)) {
          targetCropId = cropNameToId.get(cropNameKey);
        }
      }

      if (!targetCropId) {
        summary.skipped_sensor_readings += 1;
        return;
      }

      insertSensorStmt.run(
        targetCropId,
        normalizeNumeric(rawReading?.soil_moisture, null),
        normalizeNumeric(rawReading?.air_temp, null),
        normalizeNumeric(rawReading?.air_humidity, null),
        normalizeNumeric(rawReading?.light, null),
        normalizeNumeric(rawReading?.precipitation, null),
        normalizeNumeric(rawReading?.wind_speed, null),
        normalizeIsoDate(rawReading?.created_at, new Date().toISOString().slice(0, 19).replace('T', ' ')),
      );
      summary.inserted_sensor_readings += 1;
    });

    const insertGlobalStmt = db.prepare(
      'INSERT INTO edaphology_global_readings (location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    );

    globalRows.forEach(rawGlobal => {
      insertGlobalStmt.run(
        normalizeText(rawGlobal?.location_name, 'general'),
        normalizeNumeric(rawGlobal?.soil_temp, null),
        normalizeNumeric(rawGlobal?.air_temp, null),
        normalizeNumeric(rawGlobal?.air_humidity, null),
        normalizeNumeric(rawGlobal?.soil_moisture, null),
        normalizeNumeric(rawGlobal?.precipitation, null),
        normalizeNumeric(rawGlobal?.wind_speed, null),
        normalizeNumeric(rawGlobal?.ph, null),
        normalizeNumeric(rawGlobal?.conductivity, null),
        normalizeText(rawGlobal?.notes, 'Lectura global importada por dataset de usuario.'),
        normalizeIsoDate(rawGlobal?.created_at, new Date().toISOString().slice(0, 19).replace('T', ' ')),
      );
      summary.inserted_global_readings += 1;
    });

    const insertNutrientStmt = db.prepare(
      'INSERT INTO soil_nutrients (user_crop_id, nitrogen, phosphorus, potassium, nitrogen_opt_min, nitrogen_opt_max, phosphorus_opt_min, phosphorus_opt_max, potassium_opt_min, potassium_opt_max, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    );

    nutrientRows.forEach(raw => {
      let targetCropId = null;
      const explicitCropId = normalizeNumeric(raw?.user_crop_id, null);
      if (explicitCropId) {
        const crop = db.prepare('SELECT id FROM user_crops WHERE id = ? AND user_id = ?').get(explicitCropId, userId);
        if (crop) targetCropId = crop.id;
      }
      if (!targetCropId) {
        const cropNameKey = normalizeText(raw?.crop_name, '').toLowerCase();
        if (cropNameKey && cropNameToId.has(cropNameKey)) targetCropId = cropNameToId.get(cropNameKey);
      }
      if (!targetCropId) return;
      insertNutrientStmt.run(
        targetCropId,
        normalizeNumeric(raw?.nitrogen, null),
        normalizeNumeric(raw?.phosphorus, null),
        normalizeNumeric(raw?.potassium, null),
        normalizeNumeric(raw?.nitrogen_opt_min, 3.0),
        normalizeNumeric(raw?.nitrogen_opt_max, 4.0),
        normalizeNumeric(raw?.phosphorus_opt_min, 2.0),
        normalizeNumeric(raw?.phosphorus_opt_max, 3.0),
        normalizeNumeric(raw?.potassium_opt_min, 2.5),
        normalizeNumeric(raw?.potassium_opt_max, 3.5),
        normalizeText(raw?.notes, null),
        normalizeIsoDate(raw?.created_at, new Date().toISOString().slice(0, 19).replace('T', ' ')),
      );
      summary.inserted_soil_nutrients += 1;
    });

    const insertIrrigStmt = db.prepare(
      'INSERT INTO irrigation_events (user_crop_id, event_date, liters_applied, duration_minutes, method, soil_moisture_before, soil_moisture_after, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
    );

    irrigationRows.forEach(raw => {
      let targetCropId = null;
      const explicitCropId = normalizeNumeric(raw?.user_crop_id, null);
      if (explicitCropId) {
        const crop = db.prepare('SELECT id FROM user_crops WHERE id = ? AND user_id = ?').get(explicitCropId, userId);
        if (crop) targetCropId = crop.id;
      }
      if (!targetCropId) {
        const cropNameKey = normalizeText(raw?.crop_name, '').toLowerCase();
        if (cropNameKey && cropNameToId.has(cropNameKey)) targetCropId = cropNameToId.get(cropNameKey);
      }
      if (!targetCropId) return;
      insertIrrigStmt.run(
        targetCropId,
        normalizeText(raw?.event_date, new Date().toISOString().slice(0, 10)),
        normalizeNumeric(raw?.liters_applied, 0),
        normalizeNumeric(raw?.duration_minutes, null),
        normalizeText(raw?.method, 'goteo'),
        normalizeNumeric(raw?.soil_moisture_before, null),
        normalizeNumeric(raw?.soil_moisture_after, null),
        normalizeText(raw?.notes, null),
        normalizeIsoDate(raw?.created_at, new Date().toISOString().slice(0, 19).replace('T', ' ')),
      );
      summary.inserted_irrigation_events = (summary.inserted_irrigation_events || 0) + 1;
    });
  });

  tx();
  return summary;
}

// --- RUTAS DE AUTENTICACIÓN ---

router.post('/auth/register', async (req, res) => {
  const { username, password } = req.body;

  if (!username || !password) {
    return res.status(400).json({ error: 'Por favor, proporcione usuario y contraseña.' });
  }

  if (password.length < 6) {
    return res.status(400).json({ error: 'La contraseña debe tener al menos 6 caracteres.' });
  }

  try {
    const existing = stmts.findUserByUsername.get(username);
    if (existing) {
      return res.status(400).json({ error: 'El nombre de usuario ya está en uso.' });
    }

    const salt = await bcrypt.genSalt(10);
    const hash = await bcrypt.hash(password, salt);
    const result = stmts.insertUser.run(username, hash);

    res.status(201).json({
      message: 'Usuario registrado exitosamente. Por favor, inicia sesión.',
      userId: String(result.lastInsertRowid),
      username,
    });
  } catch (err) {
    console.error('Error en registro:', err.message);
    res.status(500).json({ error: 'Error en el servidor al intentar registrar el usuario.' });
  }
});

router.post('/auth/login', async (req, res) => {
  const { username, password } = req.body;

  if (!username || !password) {
    return res.status(400).json({ error: 'Faltan credenciales.' });
  }

  try {
    const user = stmts.findUserByUsername.get(username);
    if (!user) {
      return res.status(401).json({ error: 'Usuario o contraseña inválidos.' });
    }

    const isMatch = await bcrypt.compare(password, user.password_hash);
    if (!isMatch) {
      return res.status(401).json({ error: 'Usuario o contraseña inválidos.' });
    }

    const payload = {
      user: {
        id: String(user.id),
        username: user.username,
      },
    };

    jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN }, (err, token) => {
      if (err) throw err;
      res.json({
        message: 'Login exitoso.',
        token,
        userId: String(user.id),
        username: user.username,
      });
    });
  } catch (err) {
    console.error('Error en login:', err.message);
    res.status(500).json({ error: 'Error en el servidor.' });
  }
});

// --- Middleware de verificación de token (para rutas protegidas) ---
const verificarToken = (req, res, next) => {
  const authHeader = req.header('Authorization');

  if (!authHeader) {
    return res.status(401).json({ error: 'Acceso denegado. No se proporcionó token.' });
  }

  const tokenParts = authHeader.split(' ');
  if (tokenParts.length !== 2 || tokenParts[0] !== 'Bearer') {
    return res.status(401).json({ error: 'Formato de token inválido. Debe ser "Bearer <token>".' });
  }
  const token = tokenParts[1];

  if (!token) {
    return res.status(401).json({ error: 'Acceso denegado. Token ausente.' });
  }

  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.user = decoded.user;
    next();
  } catch (err) {
    res.status(401).json({ error: 'Token inválido o expirado.' });
  }
};

// --- PERFIL / CUENTA / AJUSTES ---

router.get('/profile', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const user = ensureUserSupportRows(userId);
  if (!user) {
    return res.status(404).json({ error: 'Usuario no encontrado.' });
  }

  const profile = stmts.getUserWithProfile.get(userId);
  res.json({
    user_id: userId,
    username: profile.username,
    first_name: profile.first_name || profile.username,
    last_name: profile.last_name || '',
    bio: profile.bio || '',
    location: profile.location || '',
    experience: profile.experience || '5-15 años',
    avatar_path: profile.avatar_path || 'elementos/Campesinos.jpg',
    email: profile.email || '',
    phone: profile.phone || '',
    language: profile.language || 'Español',
    lat: profile.lat,
    lon: profile.lon,
    geo_zoom: profile.geo_zoom,
    created_at: profile.created_at,
  });
});

router.put('/profile', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const user = ensureUserSupportRows(userId);
  if (!user) {
    return res.status(404).json({ error: 'Usuario no encontrado.' });
  }

  const values = pickFields(req.body || {}, PROFILE_FIELDS);
  if (!updateRow('user_profiles', 'user_id', userId, values)) {
    return res.status(400).json({ error: 'No hay cambios de perfil para guardar.' });
  }

  const profile = stmts.getUserWithProfile.get(userId);
  res.json({
    user_id: userId,
    username: profile.username,
    first_name: profile.first_name || profile.username,
    last_name: profile.last_name || '',
    bio: profile.bio || '',
    location: profile.location || '',
    experience: profile.experience || '5-15 años',
    avatar_path: profile.avatar_path || 'elementos/Campesinos.jpg',
    email: profile.email || '',
    phone: profile.phone || '',
    language: profile.language || 'Español',
    lat: profile.lat,
    lon: profile.lon,
    geo_zoom: profile.geo_zoom,
    created_at: profile.created_at,
  });
});

router.put('/account', verificarToken, async (req, res) => {
  const userId = Number(req.user.id);
  const user = ensureUserSupportRows(userId);
  if (!user) {
    return res.status(404).json({ error: 'Usuario no encontrado.' });
  }

  const values = pickFields(req.body || {}, ACCOUNT_FIELDS);
  updateRow('user_profiles', 'user_id', userId, values);

  const { currentPassword, newPassword } = req.body || {};
  let passwordChanged = false;
  if (newPassword) {
    if (String(newPassword).length < 6) {
      return res.status(400).json({ error: 'La nueva contraseña debe tener al menos 6 caracteres.' });
    }
    if (!currentPassword) {
      return res.status(400).json({ error: 'Debes indicar la contraseña actual.' });
    }
    const isMatch = await bcrypt.compare(String(currentPassword), user.password_hash);
    if (!isMatch) {
      return res.status(401).json({ error: 'La contraseña actual es incorrecta.' });
    }
    const salt = await bcrypt.genSalt(10);
    const hash = await bcrypt.hash(String(newPassword), salt);
    db.prepare('UPDATE users SET password_hash = ? WHERE id = ?').run(hash, userId);
    passwordChanged = true;
  }

  const profile = stmts.getUserWithProfile.get(userId);
  res.json({
    message: passwordChanged ? 'Cuenta y contraseña actualizadas.' : 'Cuenta actualizada.',
    password_changed: passwordChanged,
    profile: {
      user_id: userId,
      username: profile.username,
      email: profile.email || '',
      phone: profile.phone || '',
      language: profile.language || 'Español',
    },
  });
});

router.delete('/account', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const user = stmts.getUserById.get(userId);
  if (!user) {
    return res.status(404).json({ error: 'Usuario no encontrado.' });
  }

  const removeUserData = db.transaction(() => {
    const cropRows = db.prepare('SELECT id FROM user_crops WHERE user_id = ?').all(userId);
    const cropIds = cropRows.map(row => row.id);

    if (cropIds.length) {
      const placeholders = cropIds.map(() => '?').join(', ');
      db.prepare(`DELETE FROM sensor_readings WHERE user_crop_id IN (${placeholders})`).run(...cropIds);
      db.prepare(`DELETE FROM recommendations WHERE user_crop_id IN (${placeholders})`).run(...cropIds);
    }

    db.prepare('DELETE FROM calendar_events WHERE user_id = ?').run(userId);
    db.prepare('DELETE FROM user_profiles WHERE user_id = ?').run(userId);
    db.prepare('DELETE FROM user_settings WHERE user_id = ?').run(userId);
    db.prepare('DELETE FROM chat_messages WHERE user_id = ?').run(userId);
    db.prepare('DELETE FROM user_crops WHERE user_id = ?').run(userId);
    db.prepare('DELETE FROM users WHERE id = ?').run(userId);
  });

  removeUserData();
  res.status(204).send();
});

router.post('/profile/avatar', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const user = ensureUserSupportRows(userId);
  if (!user) {
    return res.status(404).json({ error: 'Usuario no encontrado.' });
  }

  try {
    const current = stmts.getUserWithProfile.get(userId);
    const avatarPath = saveImageData(req.body?.imageData, 'avatars', `${user.username}-avatar`);
    removeManagedUpload(current?.avatar_path);
    db.prepare("UPDATE user_profiles SET avatar_path = ?, updated_at = datetime('now') WHERE user_id = ?").run(avatarPath, userId);
    res.status(201).json({ avatar_path: avatarPath });
  } catch (error) {
    console.error('Error guardando avatar:', error.message);
    res.status(400).json({ error: error.message || 'No se pudo guardar el avatar.' });
  }
});

router.get('/settings', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  ensureUserSupportRows(userId);
  res.json(stmts.getUserSettings.get(userId));
});

router.put('/settings', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  ensureUserSupportRows(userId);
  const values = pickFields(req.body || {}, SETTINGS_FIELDS, (field, value) => {
    if (BOOLEAN_SETTINGS.has(field)) {
      return safeBooleanInt(Boolean(value));
    }
    if (['min_soil_moisture', 'max_temperature', 'min_air_humidity', 'pest_threshold'].includes(field)) {
      return Number(value);
    }
    return value;
  });

  if (!updateRow('user_settings', 'user_id', userId, values)) {
    return res.status(400).json({ error: 'No hay ajustes para guardar.' });
  }

  res.json(stmts.getUserSettings.get(userId));
});

// --- CALENDARIO ---

router.get('/datasets/users', verificarToken, (req, res) => {
  const users = db.prepare(`
    SELECT
      u.id,
      u.username,
      COUNT(DISTINCT c.id) AS crop_count,
      COUNT(sr.id) AS sensor_readings_count,
      MAX(sr.created_at) AS last_sensor_at
    FROM users u
    LEFT JOIN user_crops c ON c.user_id = u.id
    LEFT JOIN sensor_readings sr ON sr.user_crop_id = c.id
    GROUP BY u.id, u.username
    ORDER BY u.username ASC
  `).all();
  res.json(users);
});

router.post('/datasets/import', verificarToken, (req, res) => {
  const fallbackUserId = Number(req.user.id);
  const targetUserId = Number(req.body?.target_user_id || fallbackUserId);
  const clearExisting = Boolean(req.body?.clear_existing);

  if (!Number.isInteger(targetUserId) || targetUserId <= 0) {
    return res.status(400).json({ error: 'target_user_id invalido.' });
  }

  const targetUser = stmts.getUserById.get(targetUserId);
  if (!targetUser) {
    return res.status(404).json({ error: 'Usuario destino no encontrado.' });
  }

  try {
    const dataset = parseDatasetPayload(req.body?.dataset);
    const summary = importDatasetForUser(targetUserId, dataset, { clearExisting });
    res.status(201).json({
      message: `Dataset importado para ${targetUser.username}.`,
      target_user_id: targetUserId,
      target_username: targetUser.username,
      summary,
    });
  } catch (error) {
    console.error('Dataset import error:', error.message);
    res.status(400).json({ error: error.message || 'No se pudo importar el dataset.' });
  }
});

router.post('/datasets/bootstrap', verificarToken, (req, res) => {
  const fallbackUserId = Number(req.user.id);
  const targetUserId = Number(req.body?.target_user_id || fallbackUserId);
  const clearExisting = req.body?.clear_existing !== undefined ? Boolean(req.body?.clear_existing) : true;
  const weeks = Math.max(4, Math.min(104, Number(req.body?.weeks || 24)));
  const intervalDays = Math.max(1, Math.min(30, Number(req.body?.interval_days || 7)));

  if (!Number.isInteger(targetUserId) || targetUserId <= 0) {
    return res.status(400).json({ error: 'target_user_id invalido.' });
  }

  const targetUser = stmts.getUserById.get(targetUserId);
  if (!targetUser) {
    return res.status(404).json({ error: 'Usuario destino no encontrado.' });
  }

  try {
    const dataset = generateMonitoringDatasetTemplate(weeks, intervalDays);
    const summary = importDatasetForUser(targetUserId, dataset, { clearExisting });
    res.status(201).json({
      message: `Dataset de monitoreo generado para ${targetUser.username}.`,
      target_user_id: targetUserId,
      target_username: targetUser.username,
      weeks,
      interval_days: intervalDays,
      summary,
    });
  } catch (error) {
    console.error('Dataset bootstrap error:', error.message);
    res.status(400).json({ error: error.message || 'No se pudo generar el dataset.' });
  }
});

function generateCalendarPlanForUser(userId, includePast = false, force = false) {
  const crops = db.prepare(`
    SELECT id, crop_name, display_name, planted_at, expected_harvest_at, growth_stage, progress
    FROM user_crops
    WHERE user_id = ? AND status = 'activo'
    ORDER BY created_at DESC
  `).all(userId);
  if (!crops.length) {
    return { inserted: [], skipped: [], basis: 'Sin cultivos activos.' };
  }

  const nowIso = new Date().toISOString().slice(0, 10);
  const inserted = [];
  const skipped = [];

  const tx = db.transaction(() => {
    for (const crop of crops) {
      const rules = db.prepare(`
        SELECT crop_name, event_type_slug, day_offset, title_template, description_template,
               trigger_condition, rationale, source_doc_hint, priority
        FROM crop_calendar_rules
        WHERE crop_name IN (?, '*')
        ORDER BY priority ASC, day_offset ASC
      `).all(String(crop.crop_name || '').toLowerCase());

      const baseDate = crop.planted_at || nowIso;
      for (const rule of rules) {
        const eventDate = addDaysIso(baseDate, rule.day_offset);
        if (!eventDate) {
          skipped.push({ crop_id: crop.id, reason: 'invalid_base_date', rule });
          continue;
        }
        if (!includePast && eventDate < nowIso) {
          skipped.push({ crop_id: crop.id, reason: 'past_date', event_date: eventDate, rule: rule.title_template });
          continue;
        }

        if (!force) {
          const existing = db.prepare(`
            SELECT id FROM calendar_events
            WHERE user_id = ? AND user_crop_id = ? AND title = ? AND start_date = ?
            LIMIT 1
          `).get(
            userId,
            crop.id,
            fillRuleTemplate(rule.title_template, crop),
            eventDate
          );
          if (existing) {
            skipped.push({ crop_id: crop.id, reason: 'already_exists', event_id: existing.id, title: rule.title_template });
            continue;
          }
        }

        const typeMeta = db.prepare(`
          SELECT action_when_due, basis_notes
          FROM calendar_event_types WHERE slug = ? LIMIT 1
        `).get(rule.event_type_slug);
        const rationaleText = rule.rationale || typeMeta?.basis_notes || 'Regla agronómica programada automáticamente.';
        const sourceHint = rule.source_doc_hint ? ` Fuente: ${rule.source_doc_hint}.` : '';
        const actionText = typeMeta?.action_when_due ? ` Acción esperada: ${typeMeta.action_when_due}` : '';
        const description = [
          fillRuleTemplate(rule.description_template, crop),
          `Fundamento: ${rationaleText}.${actionText}${sourceHint}`,
          `Condición de activación: ${rule.trigger_condition || 'always'}.`
        ].join(' ');

        const result = db.prepare(`
          INSERT INTO calendar_events
            (user_id, user_crop_id, title, event_type, start_date, end_date, description, status, source_kind)
          VALUES (?, ?, ?, ?, ?, ?, ?, 'programado', 'ia')
        `).run(
          userId,
          crop.id,
          fillRuleTemplate(rule.title_template, crop),
          rule.event_type_slug,
          eventDate,
          eventDate,
          description
        );

        inserted.push({
          id: Number(result.lastInsertRowid),
          user_crop_id: crop.id,
          crop_name: crop.crop_name,
          event_type: rule.event_type_slug,
          event_date: eventDate,
          title: fillRuleTemplate(rule.title_template, crop),
          source_kind: 'ia',
        });
      }
    }
  });
  tx();
  return {
    inserted,
    skipped,
    basis: 'Reglas por cultivo + fecha de siembra + catálogos agronómicos configurables',
  };
}

router.get('/calendar/events', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  ensureUserSupportRows(userId);
  const autoGenerate = String(req.query.auto_generate ?? '1') !== '0';
  if (autoGenerate) {
    try {
      generateCalendarPlanForUser(userId, false, false);
    } catch (error) {
      console.warn('No se pudo ejecutar autogeneración de calendario:', error.message);
    }
  }
  res.json(stmts.getCalendarEvents.all(userId));
});

router.get('/calendar/event-types', verificarToken, (req, res) => {
  const rows = db.prepare(`
    SELECT slug, label, color_class, badge_class, border_color, default_priority, action_when_due, basis_notes
    FROM calendar_event_types
    ORDER BY default_priority ASC, id ASC
  `).all();
  res.json(rows);
});

router.get('/recommendations/action-types', verificarToken, (req, res) => {
  const rows = db.prepare(`
    SELECT slug, label
    FROM recommendation_action_types
    ORDER BY label ASC
  `).all();
  res.json(rows);
});

router.post('/recommendations/auto-generate', verificarToken, async (req, res) => {
  const userId = Number(req.user.id);
  const runForMonitoring = String(req.body?.context || '').toLowerCase() === 'monitoring';
  try {
    const result = await generateAutoRecommendationsForUser(userId);
    res.status(201).json({
      message: runForMonitoring
        ? `Monitoreo automático ejecutado. Recomendaciones evaluadas para cultivos activos (${result.created.length} actualizadas/creadas).`
        : `Recomendaciones automáticas evaluadas para cultivos activos (${result.created.length} actualizadas/creadas).`,
      generated_at: new Date().toISOString(),
      created: result.created,
      skipped: result.skipped,
    });
  } catch (error) {
    console.error('Auto recommendation generation error:', error.message);
    res.status(500).json({ error: 'No se pudo ejecutar la generación automática de recomendaciones.' });
  }
});

router.post('/calendar/plans/generate', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  ensureUserSupportRows(userId);
  const includePast = Boolean(req.body?.include_past);
  const force = Boolean(req.body?.force);
  const horizonDays = Number(req.body?.horizon_days ?? 21);
  const activeCrops = db.prepare(`SELECT id FROM user_crops WHERE user_id = ? AND status = 'activo'`).all(userId);
  if (!activeCrops.length) {
    return res.status(400).json({ error: 'No hay cultivos activos para planificar calendario.' });
  }

  const plan = generateCalendarPlanForUser(userId, includePast, force);
  let rolling = { inserted: [], basis: '' };
  try {
    rolling = suggestRollingMonitoringEvents(userId, Number.isFinite(horizonDays) ? horizonDays : 21);
  } catch (error) {
    console.warn('suggestRollingMonitoringEvents:', error.message);
  }

  const rollingInserted = rolling.inserted || [];
  const rulesCount = plan.inserted.length;
  const rollingCount = rollingInserted.length;

  res.status(201).json({
    message: `Plan generado: ${rulesCount} evento(s) por reglas agronómicas + ${rollingCount} visita(s) sugeridas (IA operativa).`,
    inserted: plan.inserted,
    rolling_ia: rollingInserted,
    skipped: plan.skipped,
    basis: plan.basis,
    rolling_basis: rolling.basis,
  });
});

router.post('/calendar/events', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const { title, event_type, start_date, end_date, description, user_crop_id, source_kind } = req.body || {};

  if (!title || !start_date) {
    return res.status(400).json({ error: 'El título y la fecha de inicio son obligatorios.' });
  }

  // source_kind controla el origen del evento. Solo aceptamos 'ia' o 'usuario':
  // 'ia' se usa cuando el plan llega del motor RAG (con cita a documento) o de
  // las heurísticas de IA operativa; cualquier otro valor (o vacío) cae en 'usuario'.
  const safeSourceKind = source_kind === 'ia' ? 'ia' : 'usuario';

  const result = db.prepare(`
    INSERT INTO calendar_events (user_id, user_crop_id, title, event_type, start_date, end_date, description, source_kind)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    userId,
    user_crop_id || null,
    String(title).trim(),
    event_type || 'other',
    start_date,
    end_date || start_date,
    description || null,
    safeSourceKind
  );

  res.status(201).json(db.prepare('SELECT * FROM calendar_events WHERE id = ?').get(result.lastInsertRowid));
});

router.patch('/calendar/events/:eventId', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const eventId = Number(req.params.eventId);
  const existing = db.prepare('SELECT * FROM calendar_events WHERE id = ? AND user_id = ?').get(eventId, userId);
  if (!existing) {
    return res.status(404).json({ error: 'Evento no encontrado.' });
  }

  const values = pickFields(req.body || {}, ['title', 'event_type', 'start_date', 'end_date', 'description', 'status', 'user_crop_id']);
  if (!updateRow('calendar_events', 'id', eventId, values)) {
    return res.status(400).json({ error: 'No hay cambios para guardar.' });
  }

  res.json(db.prepare('SELECT * FROM calendar_events WHERE id = ?').get(eventId));
});

router.delete('/calendar/events/:eventId', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const eventId = Number(req.params.eventId);
  const result = db.prepare('DELETE FROM calendar_events WHERE id = ? AND user_id = ?').run(eventId, userId);
  if (!result.changes) {
    return res.status(404).json({ error: 'Evento no encontrado.' });
  }
  res.status(204).send();
});

// --- UPLOADS DE CULTIVOS ---

router.post('/crops/:cropId/image', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const cropId = Number(req.params.cropId);

  try {
    const crop = db.prepare('SELECT id, user_id, crop_name, image_path FROM user_crops WHERE id = ? AND user_id = ?').get(cropId, userId);
    if (!crop) {
      return res.status(404).json({ error: 'Cultivo no encontrado.' });
    }

    const imagePath = saveImageData(req.body?.imageData, 'crops', `${crop.crop_name || 'cultivo'}-${cropId}`);
    removeManagedUpload(crop.image_path);
    db.prepare('UPDATE user_crops SET image_path = ? WHERE id = ?').run(imagePath, cropId);
    res.status(201).json({ crop_id: cropId, image_path: imagePath });
  } catch (error) {
    console.error('Error guardando imagen del cultivo:', error.message);
    const message = /no such column/i.test(error.message)
      ? 'Faltan migraciones del backend. Reinicia el backend para aplicar el nuevo esquema.'
      : (error.message || 'No se pudo guardar la imagen del cultivo.');
    res.status(400).json({ error: message });
  }
});

// --- BIBLIOTECA REAL DEL BACKEND ---

// --- NOTIFICATIONS por usuario (gap G1 cubierto por migración 0010) ---

router.get('/notifications', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const limit = Math.min(50, Math.max(1, Number(req.query.limit || 20)));
  const onlyUnread = String(req.query.unread || '').toLowerCase() === '1';
  let sql = `SELECT id, type, title, message, link_url, read_at, user_crop_id, created_at
             FROM notifications
             WHERE (user_id IS NULL OR user_id = ?)`;
  if (onlyUnread) sql += ' AND read_at IS NULL';
  sql += ' ORDER BY created_at DESC LIMIT ?';
  const rows = db.prepare(sql).all(userId, limit);
  res.json(rows);
});

router.post('/notifications', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const { type, title, message, user_crop_id, link_url } = req.body || {};
  if (!type || !title || !message) {
    return res.status(400).json({ error: 'type, title y message son obligatorios.' });
  }
  if (!['alert', 'update', 'chat'].includes(type)) {
    return res.status(400).json({ error: 'type debe ser alert | update | chat.' });
  }
  const result = db.prepare(`
    INSERT INTO notifications (user_id, user_crop_id, type, title, message, link_url)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(userId, user_crop_id || null, type, String(title).trim(), String(message).trim(), link_url || null);
  const row = db.prepare('SELECT * FROM notifications WHERE id = ?').get(result.lastInsertRowid);
  res.status(201).json(row);
});

router.patch('/notifications/:id/read', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const id = Number(req.params.id);
  const result = db.prepare(`
    UPDATE notifications
    SET read_at = datetime('now')
    WHERE id = ? AND (user_id IS NULL OR user_id = ?)
  `).run(id, userId);
  if (!result.changes) return res.status(404).json({ error: 'Notificación no encontrada.' });
  res.json({ ok: true, id });
});

router.delete('/notifications/:id', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  const id = Number(req.params.id);
  const result = db.prepare(`
    DELETE FROM notifications WHERE id = ? AND (user_id IS NULL OR user_id = ?)
  `).run(id, userId);
  if (!result.changes) return res.status(404).json({ error: 'Notificación no encontrada.' });
  res.status(204).send();
});

// --- Salud agronómica (umbrales de usuario + telemetría + ritmo vs ciclo típico) ---

router.get('/crops/agronomic-health', verificarToken, (req, res) => {
  const userId = Number(req.user.id);
  ensureUserSupportRows(userId);
  const settingsRow = stmts.getUserSettings.get(userId) || {};
  const crops = db.prepare(`
    SELECT * FROM user_crops WHERE user_id = ? AND status = 'activo' ORDER BY created_at DESC
  `).all(userId);

  const items = crops.map(crop => {
    const latest = db.prepare(`
      SELECT soil_moisture, air_temp, air_humidity, light, precipitation, created_at
      FROM sensor_readings WHERE user_crop_id = ?
      ORDER BY datetime(created_at) DESC LIMIT 1
    `).get(crop.id);
    const health = computeAgronomicHealth(crop, latest, settingsRow);
    return {
      crop_id: crop.id,
      crop_name: crop.crop_name,
      display_name: crop.display_name,
      planted_at: crop.planted_at,
      progress: crop.progress,
      latest_reading_at: latest?.created_at || null,
      ...health,
    };
  });

  res.json({ crops: items, generated_at: new Date().toISOString() });
});

// --- Catálogo dinámico de cultivos del sistema (parametrización GENERALIZACION_OK) ---
// Lee de crop_profiles. Sustituye a las antiguas listas cerradas en código.
router.get('/known-crops', verificarToken, (req, res) => {
  res.json(loadKnownCrops());
});

// --- FAQs (gap G5) ---

router.get('/faqs', verificarToken, (req, res) => {
  const { category, crop } = req.query || {};
  let sql = 'SELECT id, category, crop_name, question, answer, related_doc_id, priority, created_at FROM faqs WHERE 1=1';
  const params = [];
  if (category) { sql += ' AND category = ?'; params.push(String(category)); }
  if (crop)     { sql += ' AND (crop_name = ? OR crop_name IS NULL)'; params.push(String(crop)); }
  sql += ' ORDER BY priority ASC, id ASC';
  res.json(db.prepare(sql).all(...params));
});

// --- Library categories (gap G6) ---

router.get('/library/categories', verificarToken, (req, res) => {
  const rows = db.prepare(`
    SELECT id, slug, title, description, query_example, icon, priority
    FROM library_categories ORDER BY priority ASC, id ASC
  `).all();
  res.json(rows);
});

router.get('/library/facets', verificarToken, async (req, res) => {
  await proxyToBackend(req, res, '/library/facets');
});

router.get('/library/:docId', verificarToken, async (req, res) => {
  await proxyToBackend(req, res, `/library/${encodeURIComponent(req.params.docId)}`);
});

router.get('/library', verificarToken, async (req, res) => {
  const query = new URLSearchParams(req.query || {}).toString();
  await proxyToBackend(req, res, `/library${query ? `?${query}` : ''}`);
});

// --- Proxy a backend IA (puerto 8000) para rutas protegidas ---

router.all('/ai/*path', verificarToken, async (req, res) => {
  const targetPath = req.originalUrl.replace(/^\/api\/ai/, '/api');
  await proxyToBackend(req, res, targetPath);
});

module.exports = router;