// milpa_presenter/src/server.ts
// Fastify con CORS estricto, rate-limit, headers de seguridad y /health + /metrics.
// (Aún no llama al backend IA; eso vendrá en SPRINTs posteriores)
import fastify from "fastify";
import cors from "@fastify/cors";
import rate from "@fastify/rate-limit";
import sensible from "@fastify/sensible";
import { config } from "./config.js";
import { securityHeaders } from "./security/headers.js";
import { metricsPlugin } from "./telemetry/metrics.js";
import { queueInFlight, queueDepth, proxyTotal, proxy429, proxyTimeout, circuitOpenTotal, proxyLatency } from "./telemetry/metrics.js";
import { sanitizePlugin, sanitizeHtmlSafe } from "./security/sanitize.js";
import { buffer as streamToBuffer } from "node:stream/consumers";
import { Scheduler } from "./runtime/scheduler.js";
import { CircuitBreaker } from "./runtime/circuit.js";
const app = fastify({ trustProxy: true, logger: true });
await app.register(sensible);
await app.register(cors, { origin: config.ALLOWED_ORIGINS });
await app.register(rate, { max: 60, timeWindow: "1 minute" });
await app.register(securityHeaders);
await app.register(metricsPlugin);
// Scheduler y circuito para proxy IA
const scheduler = new Scheduler(config.MAX_CONCURRENCY, config.QUEUE_CAPACITY);
const circuit = new CircuitBreaker(config.CIRCUIT_OPEN_SECS, 30, config.CIRCUIT_MAX_P95_MS);
/** Rutas al backend que pueden tardar minutos (indexado, RAG, ingesta). */
function upstreamTimeoutMsForSuffix(suffix) {
    const path = suffix.split("?")[0].toLowerCase();
    if (path.includes("api/documents/ingest") ||
        path.includes("api/index/rebuild") ||
        path.includes("api/recommendations/generate")) {
        return config.UPSTREAM_TIMEOUT_LONG_MS;
    }
    return config.UPSTREAM_TIMEOUT_MS;
}
await app.register(sanitizePlugin);
// Cuerpos multipart: buffer hacia /ai/* (ingesta); el proxy reenvía el buffer al backend
app.addContentTypeParser(/^multipart\/.+/i, { bodyLimit: 32 * 1024 * 1024 }, async (_req, payload) => {
    return await streamToBuffer(payload);
});
// Log de diagnóstico: a qué IA_URL estamos apuntando
app.log.info({ IA_URL: config.IA_URL }, 'Configuración de IA_URL');
// Healthcheck básico
app.get("/health", async () => ({ ok: true }));
// Evita 404 ruidoso en consola del navegador
app.get("/favicon.ico", async (_req, rep) => {
    return rep.code(204).send();
});
// Redirect /ui/ -> /ui/checks (landing page)
app.get("/ui", async (_req, rep) => { rep.redirect("/ui/checks", 301); });
app.get("/ui/", async (_req, rep) => { rep.redirect("/ui/checks", 301); });
// Ruta demo: devuelve HTML con enlaces internos/externos para verificar sanitización
app.get("/demo/sanitized", async (_req, rep) => {
    const html = `
    <p>Recomendación para <em>maíz</em> en macollaje.</p>
    <ul>
      <li><a href="/doc/123?page=2" data-cite="c1" data-page="2">Ver página 2</a></li>
      <li><a href="/doc/123#bbox=10,20,100,50" data-cite="c2" data-bbox="10,20,100,50">Resaltar bbox</a></li>
      <li><a href="https://externo.ejemplo.com">Enlace externo (debe quedar #)</a></li>
    </ul>`;
    rep.header("Content-Type", "text/html; charset=utf-8");
    return sanitizeHtmlSafe(html);
});
// Ruta de clic-through con validación mínima de parámetros
app.get("/doc/:id", async (req, rep) => {
    const id = req.params.id;
    const page = Number(req.query.page ?? 1);
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
        return rep.badRequest("id inválido");
    }
    if (!Number.isFinite(page) || page < 1 || page > 5000) {
        return rep.badRequest("page inválido");
    }
    return { ok: true, id, page };
});
// Proxy simple a la salud del backend IA
app.get("/ai/health", async (_req, rep) => {
    try {
        const url = new URL("/health", config.IA_URL).toString();
        const res = await fetch(url, { method: 'GET' });
        const json = await res.json();
        return json;
    }
    catch (e) {
        rep.code(502);
        return { ok: false, error: String(e?.message ?? e) };
    }
});
// Admin: lista de usuarios con estadísticas (proxy directo al backend IA, sin auth).
app.get('/api/admin/users', async (_req, rep) => {
    try {
        const url = new URL('/admin/users', config.IA_URL).toString();
        const res = await fetch(url);
        if (!res.ok) {
            rep.code(res.status);
            return { error: 'backend error' };
        }
        return res.json();
    }
    catch (e) {
        rep.code(502);
        return { error: String(e?.message ?? e) };
    }
});
// Proxy genérico: reenvía /ai/* al backend IA preservando método, headers y cuerpo.
app.all('/ai/*', async (req, rep) => {
    try {
        proxyTotal.inc();
        // Circuit breaker: si no permite, rechazar rápido
        if (!circuit.allow()) {
            circuitOpenTotal.inc();
            rep.header('Retry-After', String(config.CIRCUIT_OPEN_SECS));
            return rep.code(503).send({ ok: false, error: 'circuit_open' });
        }
        // Construir URL destino a partir del sufijo tras /ai/
        const suffix = req.url.replace(/^\/ai\//, "");
        const target = new URL(suffix, config.IA_URL).toString();
        const upstreamTimeoutMs = upstreamTimeoutMsForSuffix(suffix);
        // Clonar headers, evitando hop-by-hop que no deben reenviarse
        const fHeaders = {};
        for (const [k, v] of Object.entries(req.headers || {})) {
            if (typeof v === 'string')
                fHeaders[k] = v;
        }
        delete fHeaders['host'];
        delete fHeaders['content-length'];
        // Preparar cuerpo segun método
        const method = (req.method || 'GET').toUpperCase();
        let body = undefined;
        if (method !== 'GET' && method !== 'HEAD') {
            if (typeof req.body === 'string' || Buffer.isBuffer(req.body)) {
                body = req.body;
            }
            else if (req.body != null) {
                // Si es objeto, asumir JSON
                fHeaders['content-type'] = fHeaders['content-type'] || 'application/json';
                body = JSON.stringify(req.body);
            }
        }
        if (method !== 'GET' && method !== 'HEAD' && Buffer.isBuffer(body)) {
            fHeaders['content-length'] = String(body.length);
            if (fHeaders['transfer-encoding']) {
                delete fHeaders['transfer-encoding'];
            }
        }
        // Encolar ejecución con control de concurrencia, deadline y métrica de latencia
        const start = Date.now();
        queueInFlight.set(scheduler.stats.inFlight);
        queueDepth.set(scheduler.stats.queued);
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(new Error("upstream_timeout")), upstreamTimeoutMs);
        try {
            const buffer = await scheduler.enqueue(async () => {
                const res = await fetch(target, { method, headers: fHeaders, body, signal: controller.signal });
                // Copiar estado y headers
                rep.code(res.status);
                res.headers.forEach((val, key) => {
                    const kl = key.toLowerCase();
                    if (kl === 'content-length' || kl === 'content-encoding')
                        return;
                    rep.header(key, val);
                });
                const ab = await res.arrayBuffer();
                return Buffer.from(ab);
            });
            const ms = Date.now() - start;
            proxyLatency.observe(ms);
            circuit.record(true, ms);
            queueInFlight.set(scheduler.stats.inFlight);
            queueDepth.set(scheduler.stats.queued);
            clearTimeout(timer);
            return buffer;
        }
        catch (e) {
            const ms = Date.now() - start;
            proxyLatency.observe(ms);
            circuit.record(false, ms);
            queueInFlight.set(scheduler.stats.inFlight);
            queueDepth.set(scheduler.stats.queued);
            clearTimeout(timer);
            if (String(e?.message ?? e) === 'queue_full') {
                proxy429.inc();
                rep.header('Retry-After', '2');
                return rep.code(429).send({ ok: false, error: 'queue_full' });
            }
            if (String(e?.message ?? e).includes('upstream_timeout') || (e?.name === 'AbortError')) {
                proxyTimeout.inc();
                return rep.code(504).send({ ok: false, error: 'upstream_timeout' });
            }
            throw e;
        }
    }
    catch (e) {
        req.log?.error({ err: e }, 'AI proxy error');
        rep.code(502);
        return { ok: false, error: 'AI proxy failed', detail: String(e?.message ?? e) };
    }
});
// Endpoint para previsualizar sanitización de HTML enviado por el usuario
app.post("/sanitize/preview", async (req, rep) => {
    const body = req.body ?? {};
    const input = String(body.html ?? "");
    const out = sanitizeHtmlSafe(input);
    rep.header("Content-Type", "text/html; charset=utf-8");
    return out;
});
// Página UI con validaciones gráficas
app.get("/ui/checks", async (_req, rep) => {
    const page = `<!doctype html>
  <html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>MILPA AI - Verificaciones del Sistema</title>
    <style>
      :root {
        --primary: #2E7D32;
        --primary-dark: #1b5e20;
        --primary-light: #81c784;
        --secondary: #10b981;
        --bg-page: #f4f6f9;
        --bg-card: #ffffff;
        --border: #e9ecef;
        --text: #111827;
        --text-muted: #6c757d;
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow-md: 0 0 15px rgba(0, 0, 0, 0.05);
        --radius: 8px;
        --radius-lg: 12px;
      }
      * { box-sizing: border-box; }
      body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
        margin: 0;
        padding: 24px;
        background: var(--bg-page);
        color: var(--text);
        line-height: 1.5;
      }
      h1 {
        font-size: 28px;
        font-weight: 700;
        margin: 0 0 8px 0;
        color: var(--text);
      }
      h2 {
        font-size: 18px;
        font-weight: 600;
        margin: 0 0 12px 0;
        color: var(--text);
      }
      h3 {
        font-size: 16px;
        font-weight: 600;
        margin: 16px 0 8px 0;
        color: var(--text);
      }
      .toolbar {
        display: flex;
        gap: 8px;
        align-items: center;
        margin-bottom: 16px;
      }
      .card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: var(--shadow-sm);
      }
      .paper {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px;
        box-shadow: var(--shadow-md);
        transition: box-shadow 0.2s;
      }
      .paper:hover {
        transform: translateY(-3px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
      }
      .ok {
        color: var(--primary);
        font-weight: 600;
      }
      .err {
        color: #ef4444;
        font-weight: 600;
      }
      code, pre {
        background: #f3f4f6;
        padding: 8px 12px;
        border-radius: 6px;
        display: block;
        overflow: auto;
        font-family: 'Fira Code', 'Cascadia Code', monospace;
        font-size: 13px;
        border: 1px solid var(--border);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 16px;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 8px 16px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--bg-card);
        color: var(--text);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        text-decoration: none;
      }
      .btn:hover {
        background: #f9fafb;
        border-color: #d1d5db;
        box-shadow: var(--shadow-sm);
      }
      .btn-primary {
        background: var(--primary);
        color: white;
        border-color: var(--primary);
      }
      .btn-primary:hover {
        background: var(--primary-dark);
        border-color: var(--primary-dark);
      }
      .row {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }
      .label {
        font-weight: 600;
        margin-top: 12px;
        margin-bottom: 4px;
        color: var(--text);
        font-size: 14px;
      }
      .muted {
        color: var(--text-muted);
        font-size: 13px;
      }
      input[type="text"], input[type="search"], textarea, select {
        padding: 8px 12px;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 14px;
        font-family: inherit;
        background: var(--bg-card);
        transition: border-color 0.2s, box-shadow 0.2s;
      }
      input:focus, textarea:focus, select:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px var(--primary-light);
      }
      hr {
        border: none;
        border-top: 1px solid var(--border);
        margin: 16px 0;
      }
      .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      .info-box {
        padding: 12px;
        background: #f9fafb;
        border-left: 3px solid var(--primary);
        border-radius: 6px;
        margin-bottom: 16px;
        font-size: 13px;
        line-height: 1.6;
      }
      .info-box strong {
        color: var(--text);
        display: inline-block;
        min-width: 120px;
      }
    </style>
  </head>
  <body>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
      <div>
        <h1 style="margin-bottom:4px; color: var(--primary)">MILPA AI - Verificaciones del Sistema</h1>
        <div class="muted">Panel de diagnóstico y validación técnica</div>
      </div>
      <div style="display:flex; gap:8px">
        <a href="/ui/ingesta" class="btn btn-primary">Ingesta de datos</a>
        <a href="/ui/query" class="btn btn-primary">Consultas RAG</a>
        <a href="/ui/library" class="btn btn-primary">Biblioteca</a>
      </div>
    </div>
    <div class="card" style="background:linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-left: 4px solid var(--primary)">
      <h2 style="margin-top:0">Guía de uso</h2>
      <p style="margin-bottom:12px">Esta página permite verificar en tiempo real, sin herramientas externas, el estado de los servicios y la correcta aplicación de las políticas de seguridad.</p>
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px">
        <div style="background:white; padding:12px; border-radius:6px; border:1px solid var(--border)">
          <strong style="color:var(--primary)">Lectura (Request)</strong>
          <div class="muted">Muestra el endpoint consultado y los parámetros enviados</div>
        </div>
        <div style="background:white; padding:12px; border-radius:6px; border:1px solid var(--border)">
          <strong style="color:var(--primary)">Salida (Response)</strong>
          <div class="muted">Respuesta exacta del servidor en formato JSON o HTML</div>
        </div>
        <div style="background:white; padding:12px; border-radius:6px; border:1px solid var(--border)">
          <strong style="color:var(--primary)">Verificación</strong>
          <div class="muted">Comprueba que la salida cumple con las políticas esperadas</div>
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="card paper" id="rag">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Consultas RAG (Diagnóstico)</h2>
          <span style="background:#dcfce7; color:#166534; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">RAG</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f0fdf4; border-left:3px solid var(--primary); border-radius:4px">
          <strong>Qué es:</strong> Prueba de consulta RAG contra el backend IA.
          <strong>Objetivo:</strong> Validar búsqueda (BM25, vector o híbrido) y generación de respuesta con citaciones.
          <strong>Comprobación:</strong> Debe devolver respuesta y fragmentos relevantes; latencia y estado HTTP se muestran si hay fallo.
        </div>
        <div class="row" style="gap:8px; align-items:stretch; flex-wrap:wrap; margin-bottom:8px">
          <input id="ragQueryInput" type="text" placeholder="Ej: ¿Cómo fertilizar maíz en etapa vegetativa?" style="flex:1; min-width:240px" />
          <select id="ragModeSelect">
            <option value="hybrid">Híbrido</option>
            <option value="bm25">BM25</option>
            <option value="vector">Vector</option>
          </select>
          <input id="ragKInput" type="number" min="1" max="20" value="5" style="width:90px" />
          <button class="btn btn-primary" id="ragSearchBtn">Buscar</button>
        </div>
        <div id="ragResults" class="muted">(sin resultados)</div>
      </div>
  <div class="card paper" id="status">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Estado de servicios</h2>
          <span style="background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">HEALTH</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid var(--primary); border-radius:4px">
          <strong>Qué es:</strong> Verifica conectividad y disponibilidad de Presenter y Backend IA.<br>
          <strong>Objetivo:</strong> Confirmar que ambos servicios responden correctamente.<br>
          <strong>Comprobación:</strong> Status "OK" indica servicio funcional. "ERROR" requiere revisión de logs.
        </div>
        <div>Presenter: <span id="presenterStatus">…</span></div>
        <div class="label">Lectura</div>
        <pre id="presenterReq">GET /health</pre>
        <div class="label">Salida</div>
        <pre id="presenterJson" class="muted">(pendiente)</pre>
        <hr />
        <div>AI Backend: <span id="aiStatus">…</span></div>
        <div class="label">Lectura</div>
        <pre id="aiReq">GET /ai/health</pre>
        <div class="label">Salida</div>
        <pre id="aiJson" class="muted">(pendiente)</pre>
        <div class="row" style="margin-top:8px"><button class="btn" id="refreshStatus">Actualizar</button></div>
      </div>

  <div class="card paper">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Demostración de sanitización</h2>
          <span style="background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">SECURITY</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid #fbbf24; border-radius:4px">
          <strong>Qué es:</strong> Valida que el HTML generado por el sistema esté limpio y seguro.<br>
          <strong>Objetivo:</strong> Prevenir XSS y garantizar enlaces seguros (internos permitidos, externos bloqueados).<br>
          <strong>Comprobación:</strong> Enlaces externos deben quedar como "#", atributos peligrosos eliminados.
        </div>
        <div class="row"><button class="btn" id="loadDemo">Cargar demo</button></div>
        <h3>Entrada (HTML original)</h3>
        <pre id="demoInput">&lt;p&gt;Recomendación para &lt;em&gt;maíz&lt;/em&gt; en macollaje.&lt;/p&gt;\n&lt;ul&gt;\n  &lt;li&gt;&lt;a href="/doc/123?page=2" data-cite="c1" data-page="2"&gt;Ver página 2&lt;/a&gt;&lt;/li&gt;\n  &lt;li&gt;&lt;a href="/doc/123#bbox=10,20,100,50" data-cite="c2" data-bbox="10,20,100,50"&gt;Resaltar bbox&lt;/a&gt;&lt;/li&gt;\n  &lt;li&gt;&lt;a href="https://externo.ejemplo.com"&gt;Enlace externo (debe quedar #)&lt;/a&gt;&lt;/li&gt;\n&lt;/ul&gt;</pre>
        <h3>Salida (HTML sanitizado)</h3>
        <div class="muted">Renderizado:</div>
        <div id="demoOutput" style="border:1px dashed #ccc; border-radius:6px; padding:10px; min-height:40px"></div>
        <div class="muted" style="margin-top:6px">HTML como texto:</div>
        <pre id="demoOutputCode" class="muted">(pendiente)</pre>
      </div>

  <div class="card paper">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Prueba manual de sanitización</h2>
          <span style="background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">SECURITY</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid #fbbf24; border-radius:4px">
          <strong>Qué es:</strong> Permite probar HTML personalizado contra el sanitizador.<br>
          <strong>Objetivo:</strong> Validar que cualquier HTML pasa por el filtro de seguridad antes de renderizarse.<br>
          <strong>Comprobación:</strong> Prueba inyectar scripts, enlaces externos y atributos maliciosos. Deben ser bloqueados.
        </div>
        <textarea id="userHtml" rows="6" style="width:100%; font-family:monospace">&lt;a href="https://phishing.tld"&gt;Click externo&lt;/a&gt; y &lt;a href="/doc/abc?page=3" data-cite="x" data-page="3"&gt;interno válido&lt;/a&gt;</textarea>
        <div class="row" style="margin-top:8px"><button class="btn" id="sanitizeBtn">Sanitizar</button></div>
        <div class="muted" style="margin-top:8px">Renderizado:</div>
        <div id="userOutput" style="border:1px dashed #ccc; border-radius:6px; padding:10px; min-height:40px;"></div>
        <div class="muted" style="margin-top:6px">HTML como texto:</div>
        <pre id="userOutputCode" class="muted">(pendiente)</pre>
      </div>

  <div class="card paper">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Validación clic-through</h2>
          <span style="background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">VALIDATION</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid #3b82f6; border-radius:4px">
          <strong>Qué es:</strong> Verifica que las rutas de documentos validen correctamente parámetros (doc_id, page).<br>
          <strong>Objetivo:</strong> Prevenir inyección de rutas y parámetros maliciosos.<br>
          <strong>Comprobación:</strong> Rutas válidas devuelven 200 OK. Rutas inválidas devuelven 400 Bad Request.
        </div>
        <div class="row">
          <button class="btn" id="clickOk">/doc/demo?page=2</button>
          <button class="btn" id="clickBad">/doc/@@@?page=-1</button>
        </div>
        <div class="label">Lectura</div>
        <pre id="clickReq" class="muted">(pendiente)</pre>
        <div class="label">Salida</div>
        <pre id="clickResult" class="muted">(pendiente)</pre>
      </div>

      <div class="card paper">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Biblioteca (repositorios cargados)</h2>
          <span style="background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">DATA</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid #3b82f6; border-radius:4px">
          <strong>Qué es:</strong> Lista documentos indexados disponibles para consulta.<br>
          <strong>Objetivo:</strong> Verificar que el backend IA devuelve correctamente el catálogo de documentos con metadatos completos.<br>
          <strong>Comprobación:</strong> Cada documento debe tener: nombre, autor, año, tipo, país, idioma, extraido_de.
        </div>
        <div class="row" style="margin-bottom:8px">
          <button class="btn" id="loadLibrary">Cargar biblioteca</button>
          <a href="/ui/library" class="btn btn-primary">Ir a Biblioteca →</a>
        </div>
        <div class="label">Lectura</div>
        <pre id="libReq" class="muted">(pendiente)</pre>
        <div class="label">Salida</div>
        <pre id="libJson" class="muted">(pendiente)</pre>
        <div class="label">Listado</div>
        <div id="libList" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-top:8px"></div>
        <div class="muted" style="margin-top:6px">Campos esperados por libro: nombre, autor, año, tipo, país, idioma, extraido_de.</div>
      </div>

      <div class="card paper">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px">
          <h2 style="margin:0">Estatus de ejecución</h2>
          <span style="background:#fce7f3; color:#9f1239; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">RUNTIME</span>
        </div>
        <div class="muted" style="margin-bottom:12px; padding:8px; background:#f9fafb; border-left:3px solid #ec4899; border-radius:4px">
          <strong>Qué es:</strong> Indicadores en tiempo real del scheduler, cola de peticiones y circuit breaker del Presenter.<br>
          <strong>Objetivo:</strong> Monitorear carga del sistema, capacidad disponible y prevención de sobrecargas.<br>
          <strong>Comprobación:</strong> "en_vuelo" muestra peticiones activas, "en_cola" las pendientes, "circuito" indica si el sistema está degradado.
        </div>
        <div class="row" style="margin-bottom:8px"><button class="btn" id="loadRuntime">Actualizar estado</button></div>
        <div class="label">Lectura</div>
        <pre id="rtReq" class="muted">(pendiente)</pre>
        <div class="label">Salida</div>
        <pre id="rtJson" class="muted">(pendiente)</pre>
        <div class="label">Indicadores</div>
        <ul id="rtList" class="muted" style="margin-top:6px"></ul>
      </div>
    </div>

    <script>
      function escapeHtml(s) {
        return String(s)
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;');
      }
      async function fetchJson(url) {
        const res = await fetch(url);
        return await res.json();
      }
      async function fetchText(url) {
        const res = await fetch(url);
        return await res.text();
      }
      async function checkStatus() {
        try {
          const presUrl = '/health';
          const res = await fetch(presUrl);
          const pres = await res.json();
          document.getElementById('presenterStatus').textContent = pres.ok ? 'OK' : 'ERROR';
          document.getElementById('presenterStatus').className = pres.ok ? 'ok' : 'err';
          document.getElementById('presenterReq').textContent = 'GET ' + presUrl + ' (HTTP ' + res.status + ')';
          document.getElementById('presenterJson').textContent = escapeHtml(JSON.stringify(pres, null, 2));
        } catch { document.getElementById('presenterStatus').textContent = 'ERROR'; document.getElementById('presenterStatus').className = 'err'; }
        try {
          const aiUrl = '/ai/health';
          const res2 = await fetch(aiUrl);
          const ai = await res2.json();
          document.getElementById('aiStatus').textContent = ai.ok ? 'OK' : 'ERROR';
          document.getElementById('aiStatus').className = ai.ok ? 'ok' : 'err';
          document.getElementById('aiReq').textContent = 'GET ' + aiUrl + ' (HTTP ' + res2.status + ')';
          document.getElementById('aiJson').textContent = escapeHtml(JSON.stringify(ai, null, 2));
        } catch { document.getElementById('aiStatus').textContent = 'ERROR'; document.getElementById('aiStatus').className = 'err'; }
      }
      async function loadDemo() {
        const url = '/demo/sanitized';
        const html = await fetchText(url);
        document.getElementById('demoOutput').innerHTML = html;
        document.getElementById('demoOutputCode').textContent = escapeHtml(html);
      }
      async function sanitizeUser() {
        const html = document.getElementById('userHtml').value;
        const res = await fetch('/sanitize/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ html }) });
        const txt = await res.text();
        document.getElementById('userOutput').innerHTML = txt;
        document.getElementById('userOutputCode').textContent = escapeHtml(txt);
      }
      async function clickOk() {
        const url = '/doc/demo?page=2';
        document.getElementById('clickReq').textContent = 'GET ' + url;
        const res = await fetch(url);
        const txt = await res.text();
        document.getElementById('clickResult').textContent = txt;
      }
      async function clickBad() {
        const url = '/doc/@@@?page=-1';
        document.getElementById('clickReq').textContent = 'GET ' + url;
        const res = await fetch(url);
        const txt = await res.text();
        document.getElementById('clickResult').textContent = txt;
      }
      function renderBookCard(b) {
        const safe = (v) => (v == null ? '-' : String(v));
        return (
          '<div style="border:1px solid #e3e3e3; border-radius:8px; padding:10px">' +
            '<div style="font-weight:600;">' + safe(b.nombre) + '</div>' +
            '<div class="muted">' + safe(b.tipo) + ' · ' + safe(b.año ?? b.anio) + '</div>' +
            '<div style="margin-top:6px">' +
              '<div><strong>Autor:</strong> ' + safe(b.autor) + '</div>' +
              '<div><strong>País:</strong> ' + safe(b.país ?? b.pais) + '</div>' +
              '<div><strong>Idioma:</strong> ' + safe(b.idioma) + '</div>' +
              '<div><strong>Extraído de:</strong> ' + safe(b.extraido_de ?? b.extraidoDe ?? b.fuente) + '</div>' +
            '</div>' +
          '</div>'
        );
      }
      async function loadLibrary() {
        const url = '/ai/library';
        document.getElementById('libReq').textContent = 'GET ' + url;
        try {
          const res = await fetch(url);
          const status = res.status;
          let data = null;
          try { data = await res.json(); } catch { data = null; }
          document.getElementById('libReq').textContent = 'GET ' + url + ' (HTTP ' + status + ')';
          document.getElementById('libJson').textContent = escapeHtml(JSON.stringify(data, null, 2));
          const listEl = document.getElementById('libList');
          listEl.innerHTML = '';
          const items = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
          if (!items.length) {
            listEl.innerHTML = '<div class="muted">(sin elementos o endpoint no disponible)</div>';
            return;
          }
          items.forEach(b => {
            listEl.insertAdjacentHTML('beforeend', renderBookCard(b));
          });
        } catch (e) {
          document.getElementById('libJson').textContent = 'Error: ' + String(e?.message ?? e);
        }
      }
      async function loadRuntime() {
        const url = '/runtime/status';
        document.getElementById('rtReq').textContent = 'GET ' + url;
        try {
          const res = await fetch(url);
          const status = res.status;
          const data = await res.json();
          document.getElementById('rtReq').textContent = 'GET ' + url + ' (HTTP ' + status + ')';
          document.getElementById('rtJson').textContent = escapeHtml(JSON.stringify(data, null, 2));
          const ul = document.getElementById('rtList');
          ul.innerHTML = '';
          const li = (t) => { const el = document.createElement('li'); el.textContent = t; return el; };
          ul.appendChild(li('en_vuelo: ' + data.en_vuelo));
          ul.appendChild(li('en_cola: ' + data.en_cola));
          ul.appendChild(li('circuito: ' + data.circuito));
          ul.appendChild(li('modo_degradado: ' + data.modo_degradado));
          ul.appendChild(li('capacidad.max_concurrency: ' + data.capacidad?.max_concurrency));
          ul.appendChild(li('capacidad.queue_capacity: ' + data.capacidad?.queue_capacity));
        } catch (e) {
          document.getElementById('rtJson').textContent = 'Error: ' + String(e?.message ?? e);
        }
      }
      document.getElementById('loadDemo').addEventListener('click', loadDemo);
      document.getElementById('sanitizeBtn').addEventListener('click', sanitizeUser);
      document.getElementById('clickOk').addEventListener('click', clickOk);
      document.getElementById('clickBad').addEventListener('click', clickBad);
      document.getElementById('loadLibrary').addEventListener('click', loadLibrary);
      document.getElementById('loadRuntime').addEventListener('click', loadRuntime);
      document.getElementById('refreshStatus').addEventListener('click', checkStatus);
      async function ragExecuteSearch(){
        const btn = document.getElementById('ragSearchBtn');
        const q = (document.getElementById('ragQueryInput').value || '').trim();
        const mode = document.getElementById('ragModeSelect').value;
        const k = parseInt(document.getElementById('ragKInput').value) || 5;
        const out = document.getElementById('ragResults');
        if(!q){ out.textContent = 'Ingresa una pregunta para consultar.'; return; }
        btn.disabled = true; const old = btn.textContent; btn.textContent = 'Buscando…';
        const t0 = performance.now();
        out.innerHTML = '<div style="padding:12px; text-align:center; color:var(--text-muted)">Buscando en la base de conocimiento…</div>';
        try{
          const res = await fetch('/ai/api/query', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ query:q, k, mode }) });
          const status = res.status;
          if(!res.ok){ throw new Error('HTTP ' + status + ' ' + res.statusText); }
          const data = await res.json();
          const dt = (performance.now() - t0).toFixed(0);
          out.innerHTML = ragRenderAnswer(data, dt);
        }catch(e){
          const dt = (performance.now() - t0).toFixed(0);
          out.innerHTML = ragRenderError(String(e?.message ?? e), dt);
        }finally{
          btn.disabled = false; btn.textContent = old;
        }
      }
      function ragEscape(s){ const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; }
      function ragRenderAnswer(data, ms){
        let html = '';
        if(data?.answer){
          html += '<div style="background:linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border:1px solid var(--primary); border-radius:8px; padding:12px; margin-bottom:12px">';
          html += '<div style="font-weight:600; color:var(--primary); margin-bottom:6px">Respuesta</div>';
          html += '<div style="color:var(--text); line-height:1.6">' + ragEscape(data.answer) + '</div>';
          if(Array.isArray(data.citations) && data.citations.length){
            html += '<div class="muted" style="margin-top:8px"><strong>Fuentes:</strong> ' + data.citations.map((c,i)=>'['+(i+1)+'] ' + ragEscape(c)).join(' ') + '</div>';
          }
          html += '<div class="muted" style="margin-top:6px; font-size:12px">Modo: <strong>' + ragEscape(data.answer_mode ?? '-') + '</strong> · Tiempo: ' + ms + ' ms</div>';
          html += '</div>';
        }
        html += '<div style="border:1px solid var(--border); border-radius:8px; padding:12px">';
        html += '<div style="font-weight:600; margin-bottom:8px">Fragmentos (' + ragEscape(data?.total_retrieved ?? (data?.fragments?.length ?? 0)) + ')</div>';
        const frags = Array.isArray(data?.fragments) ? data.fragments : [];
        if(!frags.length){ html += '<div class="muted">(sin fragmentos)</div>'; }
        frags.forEach((f, idx)=>{
          const score = Number(f?.score ?? 0);
          const previewRaw = String(f?.text ?? '');
          const preview = previewRaw.length > 500 ? previewRaw.slice(0,500) + '…' : previewRaw;
          html += '<div style="border:1px solid var(--border); border-left:4px solid var(--primary); border-radius:6px; padding:10px; margin-bottom:8px">';
          html += '<div style="display:flex; justify-content:space-between; gap:8px; margin-bottom:6px">';
          html += '<div style="font-weight:600">Fragmento ' + (idx+1) + '</div>';
          html += '<div class="muted">Relevancia ' + (score*100).toFixed(1) + '%</div>';
          html += '</div>';
          html += '<div style="color:var(--text); line-height:1.5">' + ragEscape(preview) + '</div>';
          html += '<div class="muted" style="margin-top:6px; display:flex; gap:12px; flex-wrap:wrap">';
          html += '<span>Título: ' + ragEscape(f?.doc_title ?? f?.doc_id ?? '-') + '</span>';
          if(f?.page_start != null){ html += '<span>Página ' + ragEscape(String(f.page_start)) + '</span>'; }
          html += '<span>ID: ' + ragEscape(String(f?.doc_id ?? '').slice(0,8)) + '</span>';
          html += '</div>';
          html += '</div>';
        });
        html += '</div>';
        return html;
      }
      function ragRenderError(msg, ms){
        return '<div style="border-left:4px solid #dc2626; border:1px solid var(--border); border-radius:8px; padding:12px">' +
               '<div style="font-weight:600; color:#dc2626; margin-bottom:6px">Error en la consulta</div>' +
               '<div>' + ragEscape(msg) + '</div>' +
               '<div class="muted" style="margin-top:6px; font-size:12px">Tiempo: ' + ms + ' ms</div>' +
               '</div>';
      }
      const ragBtn = document.getElementById('ragSearchBtn');
      if (ragBtn) {
        ragBtn.addEventListener('click', ragExecuteSearch);
        document.getElementById('ragQueryInput').addEventListener('keypress', (e)=>{ if(e.key==='Enter') ragExecuteSearch(); });
      }
      checkStatus();
    </script>
  </body>
  </html>`;
    rep.header("Content-Type", "text/html; charset=utf-8");
    return page;
});
// Página: Biblioteca (listado)
app.get('/ui/library', async (_req, rep) => {
    const page = `<!doctype html>
  <html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Milpa • Biblioteca</title>
    <style>
      :root {
        --primary: #10b981;
        --primary-dark: #059669;
        --primary-light: #d1fae5;
        --secondary: #6366f1;
        --bg-page: #f9fafb;
        --bg-card: #ffffff;
        --border: #e5e7eb;
        --text: #111827;
        --text-muted: #6b7280;
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        --radius: 8px;
        --radius-lg: 12px;
      }
      * { box-sizing: border-box; }
      body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
        margin: 0;
        padding: 24px;
        background: var(--bg-page);
        color: var(--text);
        line-height: 1.5;
      }
      h1 {
        font-size: 28px;
        font-weight: 700;
        margin: 0 0 8px 0;
        color: var(--text);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
        margin-top: 16px;
      }
      .card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px;
        box-shadow: var(--shadow-md);
        transition: transform 0.2s, box-shadow 0.2s;
      }
      .card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
      }
      .paper {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 16px;
        box-shadow: var(--shadow-md);
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 8px 16px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--bg-card);
        color: var(--text);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        text-decoration: none;
      }
      .btn:hover {
        background: #f9fafb;
        border-color: #d1d5db;
        box-shadow: var(--shadow-sm);
      }
      .btn-primary {
        background: var(--primary);
        color: white;
        border-color: var(--primary);
      }
      .btn-primary:hover {
        background: var(--primary-dark);
        border-color: var(--primary-dark);
      }
      .muted {
        color: var(--text-muted);
        font-size: 13px;
        margin-bottom: 16px;
      }
      a.btn {
        text-decoration: none;
        display: inline-block;
      }
      .filters {
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: 12px;
        align-items: start;
        background: var(--bg-card);
        padding: 16px;
        border-radius: var(--radius);
        border: 1px solid var(--border);
        margin-bottom: 16px;
        box-shadow: var(--shadow-sm);
      }
      .panel {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 12px;
      }
      .panel-title {
        font-weight: 600;
        font-size: 13px;
        color: var(--text);
        margin-bottom: 8px;
      }
      .scroll {
        max-height: 200px;
        overflow: auto;
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 6px;
        background: #fafafa;
      }
      input[type="text"], input[type="search"], select {
        padding: 8px 12px;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 14px;
        font-family: inherit;
        background: var(--bg-card);
        transition: border-color 0.2s, box-shadow 0.2s;
      }
      input:focus, select:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px var(--primary-light);
      }
      .pagination {
        display: flex;
        gap: 12px;
        align-items: center;
        margin-top: 16px;
        padding: 12px;
        background: var(--bg-card);
        border-radius: var(--radius);
        border: 1px solid var(--border);
      }
      /* Upload module */
      .upload-panel {
        display: none;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: var(--shadow-md);
      }
      .upload-panel.open { display: block; }
      .drop-zone {
        border: 2px dashed var(--border);
        border-radius: var(--radius);
        padding: 32px;
        text-align: center;
        cursor: pointer;
        transition: all 0.2s;
        background: #fafafa;
        margin-bottom: 16px;
      }
      .drop-zone:hover, .drop-zone.dragover {
        border-color: var(--primary);
        background: var(--primary-light);
      }
      .drop-zone .icon { font-size: 36px; margin-bottom: 8px; }
      .meta-form {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 12px;
        margin-bottom: 16px;
      }
      .meta-form label { font-size: 13px; font-weight: 500; display:flex; flex-direction:column; gap:4px; }
      .progress-bar {
        height: 8px;
        background: var(--border);
        border-radius: 4px;
        overflow: hidden;
        margin-top: 12px;
        display: none;
      }
      .progress-bar .fill {
        height: 100%;
        width: 0%;
        background: var(--primary);
        border-radius: 4px;
        transition: width 0.3s;
      }
      .status-msg {
        font-size: 13px;
        margin-top: 8px;
        min-height: 20px;
      }
      .status-msg.error { color: #dc2626; }
      .status-msg.success { color: var(--primary-dark); }
      .btn-upload {
        background: var(--secondary);
        color: white;
        border-color: var(--secondary);
      }
      .btn-upload:hover {
        background: #4f46e5;
        border-color: #4f46e5;
      }
    </style>
  </head>
  <body>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
      <div>
        <h1 style="margin-bottom:4px">Biblioteca</h1>
        <div class="muted">Explora y filtra los documentos disponibles. Usa los filtros avanzados para encontrar exactamente lo que necesitas.</div>
      </div>
      <div style="display:flex; gap:8px">
        <button class="btn btn-upload" id="btnToggleUpload">+ Cargar documento</button>
        <a href="/ui/query" class="btn btn-primary">Consultas RAG</a>
        <a href="/ui/checks" class="btn">&larr; Verificaciones</a>
      </div>
    </div>

    <!-- Upload Panel -->
    <div class="upload-panel" id="uploadPanel">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px">
        <div style="font-weight:600; font-size:16px">Cargar nuevo documento</div>
        <button class="btn" id="btnCloseUpload" style="padding:4px 10px">X</button>
      </div>
      <div class="drop-zone" id="dropZone">
        <div class="icon">&#128196;</div>
        <div style="font-weight:500; margin-bottom:4px">Arrastra un archivo aqui o haz clic para seleccionar</div>
        <div class="muted" style="margin:0">PDF, DOCX o TXT (max 25 MB)</div>
        <input type="file" id="fileInput" accept=".pdf,.docx,.txt,.md,.text" style="display:none" />
      </div>
      <div id="fileInfo" style="font-size:13px; color:var(--primary-dark); margin-bottom:12px; display:none"></div>
      <div class="meta-form">
        <label style="flex-direction:row; align-items:center; gap:8px; cursor:pointer">
          <input type="checkbox" id="useManualMeta" />
          <span>Permitir título, autor y año manuales (si está desmarcado, se usan solo metadatos del archivo / PDF)</span>
        </label>
        <div id="manualMetaFields" style="display:none; flex-direction:column; gap:8px">
        <label>Titulo <input type="text" id="upTitle" placeholder="(del PDF o nombre de archivo si vacio)" /></label>
        <label>Autor <input type="text" id="upAuthor" placeholder="(del PDF si vacio)" /></label>
        <label>Anio <input type="number" id="upYear" placeholder="(del PDF o archivo si vacio)" min="1900" max="2100" /></label>
        </div>
        <label>Licencia
          <select id="upLicense">
            <option value="public_domain">Dominio publico</option>
            <option value="institutional">Institucional</option>
            <option value="permitted">Permitido</option>
            <option value="normative">Normativo</option>
          </select>
        </label>
        <label>Clasificacion
          <select id="upClass">
            <option value="Publico">Publico</option>
            <option value="Interno">Interno</option>
            <option value="Restringido">Restringido</option>
          </select>
        </label>
        <p class="muted" style="font-size:12px; margin:8px 0 0; line-height:1.4">
          Licencia y visibilidad siempre las eliges aquí. Activa el recuadro superior si quieres sobrescribir
          título, autor o año; los campos que dejes vacíos se rellenan con los metadatos del propio documento
          (PDF /Info) o con el nombre del archivo.
        </p>
      </div>
      <div style="display:flex; gap:8px; align-items:center">
        <button class="btn btn-primary" id="btnIngest" disabled>Procesar e indexar</button>
        <span class="muted" id="uploadHint">Selecciona un archivo primero</span>
      </div>
      <div class="progress-bar" id="progressBar"><div class="fill" id="progressFill"></div></div>
      <div class="status-msg" id="statusMsg"></div>
    </div>

    <div class="filters">
      <div>
        <div class="panel-title">Búsqueda</div>
        <input id="q" type="search" placeholder="Buscar por nombre, autor o fuente" style="width:100%; margin-bottom:8px" />
        <label style="display:flex; gap:6px; align-items:center; font-size:13px">
          <input type="checkbox" id="word" />
          <span>Buscar por palabra exacta (AND)</span>
        </label>
        <div style="margin-top:8px; display:flex; gap:8px">
          <button class="btn btn-primary" id="btnBuscar">Buscar</button>
          <button class="btn" id="btnLimpiar">Limpiar</button>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title">Año</div>
        <select id="year" style="width:100%"><option value="">(Todos)</option></select>
      </div>
      <div class="panel">
        <div class="panel-title">Autores (A→Z)</div>
        <input id="authorSearch" type="search" placeholder="Filtrar autores" style="width:100%; margin-bottom:6px" />
        <div class="scroll"><ul id="authorList" style="list-style:none; padding-left:0; margin:0"></ul></div>
      </div>
    </div>
    <div class="grid" id="list"></div>
    <div class="pagination">
      <button class="btn" id="prev">← Anterior</button>
      <div class="muted" id="pageInfo">(página 1)</div>
      <button class="btn btn-primary" id="next">Siguiente →</button>
    </div>
    <script>
      function esc(s){return String(s).replaceAll('<','&lt;').replaceAll('>','&gt;')}
      function card(item){
        const nombre = esc(item.nombre ?? item.id);
        const etiqueta = esc(((item.autor ?? 'Sin autor') + (item['año'] ? ' · ' + item['año'] : '')));
        const url = '/ui/library/' + encodeURIComponent(item.id);
        return '<div class="card">' +
               '<div style="font-weight:600; font-size:16px; margin-bottom:6px; color:var(--text)">' + nombre + '</div>' +
               '<div class="muted">' + etiqueta + '</div>' +
               '<div style="margin-top:12px"><a class="btn btn-primary" href="' + url + '">Ver detalle</a></div>' +
               '</div>';
      }
      let state = { q: '', offset: 0, limit: 12, total: 0, year: '', author: '', word: false, authorsAll: [], yearsAll: [] };
      async function loadFacets(){
        const res = await fetch('/ai/library/facets'); const f = await res.json();
        state.authorsAll = Array.isArray(f?.authors) ? f.authors : [];
        state.yearsAll = Array.isArray(f?.years) ? f.years : [];
        const sel = document.getElementById('year'); sel.innerHTML = '<option value="">(Todos)</option>' + state.yearsAll.map(y => '<option>'+y+'</option>').join('');
        renderAuthorList();
      }
      function renderAuthorList(){
        const ul = document.getElementById('authorList');
        const q = (document.getElementById('authorSearch').value || '').toLowerCase();
        ul.innerHTML = '';
        const allLi = document.createElement('li');
        allLi.innerHTML = '<label style="display:flex; gap:6px; align-items:center"><input type="radio" name="author" value="" ' + (state.author ? '' : 'checked') + ' /> <span>(Todos)</span></label>';
        ul.appendChild(allLi);
        state.authorsAll.filter(a => !q || String(a).toLowerCase().includes(q)).forEach(a => {
          const li = document.createElement('li');
          const id = 'a_' + btoa(unescape(encodeURIComponent(a))).replace(/=+$/,'');
          li.innerHTML = '<label style="display:flex; gap:6px; align-items:center"><input type="radio" name="author" value="'+esc(a)+'" ' + (state.author===a ? 'checked' : '') + ' /> <span>'+esc(a)+'</span></label>';
          ul.appendChild(li);
        });
      }
      async function load(){
        const params = new URLSearchParams();
        if (state.q) params.set('q', state.q);
        if (state.word) params.set('word', 'true');
        if (state.year) params.set('year', state.year);
        if (state.author) params.set('author', state.author);
        params.set('offset', String(state.offset));
        params.set('limit', String(state.limit));
        const res = await fetch('/ai/library?' + params.toString());
        const data = await res.json();
        const items = Array.isArray(data?.items) ? data.items : [];
        state.total = Number(data?.total ?? 0);
        const el = document.getElementById('list');
        if(!items.length){ el.innerHTML = '<div class="muted">(sin elementos)</div>'; return; }
        el.innerHTML='';
        items.forEach(it => el.insertAdjacentHTML('beforeend', card(it)));
  const pageNo = Math.floor(state.offset / state.limit) + 1;
  const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
  document.getElementById('pageInfo').textContent = 'página ' + pageNo + ' de ' + totalPages + ' (total ' + state.total + ')';
      }
  document.getElementById('btnBuscar').addEventListener('click', () => { state.q = (document.getElementById('q').value || '').trim(); state.word = document.getElementById('word').checked; state.offset = 0; load(); });
      document.getElementById('btnLimpiar').addEventListener('click', () => {
        state.q=''; state.word=false; state.year=''; state.author=''; state.offset=0;
        document.getElementById('q').value='';
        document.getElementById('word').checked=false;
        document.getElementById('year').value='';
        document.getElementById('authorSearch').value='';
        renderAuthorList();
        load();
      });
  document.getElementById('year').addEventListener('change', (e) => { state.year = (e.target.value || '').trim(); state.offset = 0; load(); });
  document.getElementById('authorSearch').addEventListener('input', renderAuthorList);
  document.getElementById('authorList').addEventListener('change', (e) => { if (e.target && e.target.name === 'author') { state.author = e.target.value; state.offset = 0; load(); } });
      document.getElementById('prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
      document.getElementById('next').addEventListener('click', () => { const next = state.offset + state.limit; if (next < state.total) { state.offset = next; load(); } });
  window.addEventListener('pageshow', (e) => { if (e.persisted) { loadFacets().then(load); } });

  // --- Upload Module (mismo origen: proxy /ai/* evita connect-src; CSP también admite :8000 vía headers.ts)
  const INGEST_URL = '/ai/api/documents/ingest';
  let selectedFile = null;
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileInfo = document.getElementById('fileInfo');
  const btnIngest = document.getElementById('btnIngest');
  const uploadHint = document.getElementById('uploadHint');
  const progressBar = document.getElementById('progressBar');
  const progressFill = document.getElementById('progressFill');
  const statusMsg = document.getElementById('statusMsg');
  const useManualMeta = document.getElementById('useManualMeta');
  const manualMetaFields = document.getElementById('manualMetaFields');

  function syncManualMeta() {
    const on = useManualMeta && useManualMeta.checked;
    if (manualMetaFields) {
      manualMetaFields.style.display = on ? 'flex' : 'none';
    }
    if (!on) {
      const t = document.getElementById('upTitle');
      const a = document.getElementById('upAuthor');
      const y = document.getElementById('upYear');
      if (t) t.value = '';
      if (a) a.value = '';
      if (y) y.value = '';
    }
  }
  useManualMeta && useManualMeta.addEventListener('change', syncManualMeta);
  syncManualMeta();

  document.getElementById('btnToggleUpload').addEventListener('click', () => {
    document.getElementById('uploadPanel').classList.toggle('open');
  });
  document.getElementById('btnCloseUpload').addEventListener('click', () => {
    document.getElementById('uploadPanel').classList.remove('open');
  });

  function selectFile(f) {
    if (!f) return;
    const maxMB = 25;
    if (f.size > maxMB * 1024 * 1024) {
      statusMsg.textContent = 'Archivo demasiado grande (max ' + maxMB + ' MB)';
      statusMsg.className = 'status-msg error';
      return;
    }
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['pdf','docx','txt','md','text'].includes(ext)) {
      statusMsg.textContent = 'Tipo de archivo no soportado. Usa PDF, DOCX o TXT.';
      statusMsg.className = 'status-msg error';
      return;
    }
    selectedFile = f;
    fileInfo.textContent = 'Archivo: ' + f.name + ' (' + (f.size / 1024).toFixed(1) + ' KB)';
    fileInfo.style.display = 'block';
    btnIngest.disabled = false;
    uploadHint.textContent = '';
    statusMsg.textContent = '';
    statusMsg.className = 'status-msg';
  }

  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => { if (e.target.files.length) selectFile(e.target.files[0]); });
  dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
  });

  btnIngest.addEventListener('click', async () => {
    if (!selectedFile) return;
    btnIngest.disabled = true;
    progressBar.style.display = 'block';
    progressFill.style.width = '10%';
    statusMsg.textContent = 'Subiendo archivo...';
    statusMsg.className = 'status-msg';

    const fd = new FormData();
    fd.append('file', selectedFile);
    const license = document.getElementById('upLicense').value;
    const classification = document.getElementById('upClass').value;
    if (useManualMeta && useManualMeta.checked) {
      const title = (document.getElementById('upTitle').value || '').trim();
      const author = (document.getElementById('upAuthor').value || '').trim();
      const year = (document.getElementById('upYear').value || '').trim();
      if (title) fd.append('title', title);
      if (author) fd.append('author', author);
      if (year) fd.append('year', year);
    }
    fd.append('license', license);
    fd.append('classification', classification);

    try {
      progressFill.style.width = '30%';
      statusMsg.textContent = 'Procesando y extrayendo texto...';
      const res = await fetch(INGEST_URL, { method: 'POST', body: fd });
      progressFill.style.width = '80%';

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Error ' + res.status);
      }

      const data = await res.json();
      progressFill.style.width = '100%';
      statusMsg.innerHTML = '<strong>Documento cargado exitosamente.</strong> ' +
        data.fragments + ' fragmentos extraidos, ' + data.indexed + ' indexados. ' +
        '<a href="/ui/library/' + encodeURIComponent(data.doc_id) + '">Ver detalle</a>';
      statusMsg.className = 'status-msg success';

      // Reset form
      selectedFile = null;
      fileInput.value = '';
      fileInfo.style.display = 'none';
      document.getElementById('upTitle').value = '';
      document.getElementById('upAuthor').value = '';
      document.getElementById('upYear').value = '';
      uploadHint.textContent = 'Selecciona un archivo primero';

      // Refresh library and facets
      await loadFacets();
      state.offset = 0;
      await load();
    } catch (e) {
      statusMsg.textContent = 'Error: ' + e.message;
      statusMsg.className = 'status-msg error';
      btnIngest.disabled = false;
    }
    setTimeout(() => { progressBar.style.display = 'none'; progressFill.style.width = '0%'; }, 3000);
  });

  loadFacets().then(load);
    </script>
  </body>
  </html>`;
    rep.header('Content-Type', 'text/html; charset=utf-8');
    return page;
});
// Página: Detalle de documento con vistas Web y Técnica
app.get('/ui/library/:docId', async (req, rep) => {
    const docId = req.params.docId;
    const page = `<!doctype html>
  <html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Milpa • Detalle</title>
    <style>
      :root {
        --primary: #10b981;
        --primary-dark: #059669;
        --primary-light: #d1fae5;
        --bg-page: #f9fafb;
        --bg-card: #ffffff;
        --border: #e5e7eb;
        --text: #111827;
        --text-muted: #6b7280;
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        --radius: 8px;
      }
      * { box-sizing: border-box; }
      body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
        margin: 0;
        padding: 24px;
        background: var(--bg-page);
        color: var(--text);
        line-height: 1.5;
      }
      h1 {
        font-size: 28px;
        font-weight: 700;
        margin: 16px 0 8px 0;
        color: var(--text);
      }
      h3 {
        font-size: 16px;
        font-weight: 600;
        margin: 16px 0 8px 0;
      }
      .tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 16px;
        border-bottom: 2px solid var(--border);
      }
      .tab {
        padding: 10px 20px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--text-muted);
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
        transition: all 0.2s;
      }
      .tab:hover {
        color: var(--primary);
      }
      .active {
        color: var(--primary);
        border-bottom-color: var(--primary);
      }
      .muted {
        color: var(--text-muted);
        font-size: 13px;
      }
      table {
        border-collapse: collapse;
        width: 100%;
        margin: 12px 0;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        overflow: hidden;
      }
      th, td {
        border: 1px solid var(--border);
        padding: 10px 12px;
        text-align: left;
        font-size: 13px;
      }
      th {
        background: #f9fafb;
        font-weight: 600;
        color: var(--text);
      }
      td {
        color: var(--text);
      }
      .kbd {
        font-family: 'Fira Code', 'Cascadia Code', monospace;
        font-size: 12px;
        background: #f3f4f6;
        padding: 16px;
        border-radius: var(--radius);
        border: 1px solid var(--border);
        overflow: auto;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        padding: 8px 16px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--bg-card);
        color: var(--text);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        text-decoration: none;
      }
      .btn:hover {
        background: #f9fafb;
        box-shadow: var(--shadow-sm);
      }
      a { color: var(--primary); text-decoration: none; }
      a:hover { text-decoration: underline; }
      .content-box {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 20px;
        box-shadow: var(--shadow-sm);
      }
      .meta-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
        margin: 12px 0;
      }
      .meta-item {
        padding: 8px;
        background: #f9fafb;
        border-radius: 6px;
        border: 1px solid var(--border);
      }
      .meta-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      .meta-value {
        font-size: 14px;
        color: var(--text);
        margin-top: 4px;
      }
    </style>
  </head>
  <body>
    <div style="display:flex; gap:8px; margin-bottom:16px">
      <a href="/ui/library" class="btn">← Biblioteca</a>
      <a href="/ui/checks" class="btn">← Checks</a>
    </div>
    <h1>Detalle del documento</h1>
    <div class="tabs">
      <button class="tab active" id="tabWeb">Vista Web</button>
      <button class="tab" id="tabTech">Vista Técnica (JSON)</button>
    </div>
    <div id="webView" class="content-box"></div>
    <pre id="techView" class="kbd" style="display:none"></pre>
    <script>
      const docId = ${JSON.stringify(docId)};
      function esc(s){return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
      function renderWeb(d){
        let html = '';
        html += '<h2 style="margin-top:0">' + esc(d.nombre ?? d.doc_id) + '</h2>';
        html += '<div class="muted" style="margin-bottom:20px">' + esc((d.tipo ?? '-') + (d['año'] ? ' · ' + d['año'] : '')) + '</div>';
        
        html += '<div class="meta-grid">';
        html += '<div class="meta-item"><div class="meta-label">Autor</div><div class="meta-value">' + esc(d.autor ?? 'No especificado') + '</div></div>';
        html += '<div class="meta-item"><div class="meta-label">Idioma</div><div class="meta-value">' + esc(d.idioma ?? 'No especificado') + '</div></div>';
        html += '<div class="meta-item"><div class="meta-label">Clasificación</div><div class="meta-value">' + esc(d.classification ?? 'No especificado') + '</div></div>';
        html += '<div class="meta-item"><div class="meta-label">Licencia</div><div class="meta-value">' + esc(d.license ?? 'No especificado') + '</div></div>';
        html += '</div>';

        html += '<div style="margin-top:16px"><strong>Extraído de:</strong> ' + esc(d.extraido_de ?? 'N/A') + '</div>';

        // Fragmentos de texto
        if (Array.isArray(d.fragments) && d.fragments.length) {
          html += '<h3 style="margin-top:24px">Contenido del documento</h3>';
          html += '<div style="max-height:400px; overflow-y:auto; border:1px solid var(--border); border-radius:var(--radius); padding:16px; background:#fafafa">';
          d.fragments.slice(0, 10).forEach((frag, idx) => {
            const text = frag.text || frag.content || frag;
            html += '<div style="margin-bottom:16px; padding-bottom:16px; border-bottom:1px solid var(--border)">';
            html += '<div style="font-size:12px; color:var(--text-muted); margin-bottom:4px">Fragmento ' + (idx+1) + '</div>';
            html += '<div style="font-size:14px; line-height:1.6">' + esc(String(text).substring(0, 500)) + (String(text).length > 500 ? '...' : '') + '</div>';
            html += '</div>';
          });
          if (d.fragments.length > 10) {
            html += '<div class="muted">(Mostrando primeros 10 de ' + d.fragments.length + ' fragmentos)</div>';
          }
          html += '</div>';
        } else {
          html += '<div class="muted" style="margin-top:20px">(No se extrajeron fragmentos de texto de este documento)</div>';
        }

        // Tablas
        if (Array.isArray(d.tables) && d.tables.length) {
          html += '<h3 style="margin-top:24px">Tablas extraídas</h3>';
          d.tables.forEach((t, idx) => {
            html += '<div style="margin-top:16px"><strong>Tabla ' + (idx+1) + '</strong> <span class="muted">(página ' + esc(String(t.page)) + ')</span></div>';
            if (Array.isArray(t.headers) && t.headers.length) {
              html += '<table><thead><tr>' + t.headers.map(h => '<th>' + esc(h) + '</th>').join('') + '</tr></thead><tbody>';
              (t.rows || []).forEach(r => { html += '<tr>' + r.map(c => '<td>' + esc(String(c)) + '</td>').join('') + '</tr>'; });
              html += '</tbody></table>';
            } else {
              html += '<div class="muted">(tabla sin encabezados detectados)</div>';
            }
            // Desglose
            html += '<details style="margin-top:8px"><summary style="cursor:pointer; color:var(--primary)">Ver desglose por fila</summary>';
            html += '<ul class="muted" style="margin-top:8px">';
            if (Array.isArray(t.headers) && t.headers.length && Array.isArray(t.rows)){
              t.rows.forEach((r, i) => {
                const pares = t.headers.map((h, j) => h + ': ' + (r[j] ?? '-'));
                html += '<li>' + esc(pares.join(' | ')) + '</li>';
              });
            } else {
              html += '<li>(sin filas)</li>';
            }
            html += '</ul></details>';
          });
        } else {
          html += '<div class="muted" style="margin-top:20px">(No se detectaron tablas en este documento)</div>';
        }
        return html;
      }

      async function load(){
        const res = await fetch('/ai/library/' + encodeURIComponent(docId));
        const data = await res.json();
        document.getElementById('webView').innerHTML = renderWeb(data);
        document.getElementById('techView').textContent = JSON.stringify(data, null, 2);
      }
      function selectTab(which){
        const webBtn = document.getElementById('tabWeb');
        const techBtn = document.getElementById('tabTech');
        const web = document.getElementById('webView');
        const tech = document.getElementById('techView');
        if (which === 'web'){
          webBtn.classList.add('active'); techBtn.classList.remove('active');
          web.style.display='block'; tech.style.display='none';
        } else {
          techBtn.classList.add('active'); webBtn.classList.remove('active');
          tech.style.display='block'; web.style.display='none';
        }
      }
      document.getElementById('tabWeb').addEventListener('click', () => selectTab('web'));
      document.getElementById('tabTech').addEventListener('click', () => selectTab('tech'));
      load();
    </script>
  </body>
  </html>`;
    rep.header('Content-Type', 'text/html; charset=utf-8');
    return page;
});
// Página: Consultas RAG
app.get('/ui/query', async (_req, rep) => {
    const page = `<!doctype html>
  <html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>MILPA AI - Consultas RAG</title>
    <style>
      :root {
        --primary: #2E7D32;
        --primary-dark: #1b5e20;
        --primary-light: #81c784;
        --secondary: #10b981;
        --bg-page: #f4f6f9;
        --bg-card: #ffffff;
        --border: #e9ecef;
        --text: #111827;
        --text-muted: #6c757d;
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow-md: 0 0 15px rgba(0, 0, 0, 0.05);
        --radius: 8px;
      }
      * { box-sizing: border-box; }
      body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
        margin: 0;
        padding: 24px;
        background: var(--bg-page);
        color: var(--text);
        line-height: 1.5;
      }
      h1 {
        font-size: 28px;
        font-weight: 700;
        margin: 0 0 8px 0;
        color: var(--primary);
      }
      h2 {
        font-size: 20px;
        font-weight: 600;
        margin: 20px 0 12px 0;
        color: var(--text);
      }
      h3 {
        font-size: 16px;
        font-weight: 600;
        margin: 16px 0 8px 0;
      }
      .nav {
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 8px 16px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--bg-card);
        color: var(--text);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        text-decoration: none;
      }
      .btn:hover {
        background: #f9fafb;
        border-color: #d1d5db;
        box-shadow: var(--shadow-sm);
        transform: translateY(-2px);
      }
      .btn-primary {
        background: var(--primary);
        color: white;
        border-color: var(--primary);
        font-weight: 600;
      }
      .btn-primary:hover {
        background: var(--primary-dark);
        border-color: var(--primary-dark);
      }
      .card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: var(--shadow-md);
      }
      .card-header {
        font-weight: 600;
        font-size: 16px;
        margin-bottom: 16px;
        padding-bottom: 12px;
        border-bottom: 2px solid var(--border);
        color: var(--text);
      }
      .search-box {
        position: relative;
        margin-bottom: 16px;
      }
      .search-input {
        width: 100%;
        padding: 14px 20px 14px 50px;
        border: 2px solid var(--border);
        border-radius: 12px;
        font-size: 16px;
        font-family: inherit;
        background: var(--bg-card);
        transition: all 0.2s;
      }
      .search-input:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 4px rgba(46, 125, 50, 0.1);
      }
      .search-icon {
        position: absolute;
        left: 18px;
        top: 50%;
        transform: translateY(-50%);
        color: var(--text-muted);
        font-size: 18px;
      }
      .muted {
        color: var(--text-muted);
        font-size: 13px;
      }
      .info-box {
        background: #f0fdf4;
        border-left: 4px solid var(--primary);
        padding: 12px 16px;
        border-radius: 6px;
        margin-bottom: 16px;
        font-size: 14px;
        line-height: 1.6;
      }
      .spinner {
        border: 4px solid var(--border);
        border-top: 4px solid var(--primary);
        border-radius: 50%;
        width: 40px;
        height: 40px;
        animation: spin 1s linear infinite;
        margin: 0 auto 1rem;
      }
      @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
      .answer-box {
        background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
        border: 1px solid var(--primary);
        border-radius: var(--radius);
        padding: 20px;
        margin-bottom: 20px;
      }
      .answer-title {
        font-weight: 700;
        font-size: 18px;
        color: var(--primary);
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .answer-text {
        color: var(--text);
        line-height: 1.7;
        font-size: 15px;
      }
      .fragment-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-left: 4px solid var(--primary);
        border-radius: var(--radius);
        padding: 16px;
        margin-bottom: 12px;
        transition: all 0.3s;
      }
      .fragment-card:hover {
        transform: translateX(5px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      }
      .fragment-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }
      .fragment-title {
        font-weight: 600;
        font-size: 15px;
        color: var(--text);
      }
      .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        background: var(--primary);
        color: white;
      }
      .badge-success {
        background: var(--secondary);
      }
      .fragment-text {
        color: var(--text);
        line-height: 1.6;
        margin-bottom: 10px;
        font-size: 14px;
      }
      .fragment-meta {
        color: var(--text-muted);
        font-size: 13px;
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
      }
      .meta-item {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .settings-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
      }
      .setting-item {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .setting-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--text);
      }
      select, input[type="number"] {
        padding: 8px 12px;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 14px;
        font-family: inherit;
        background: var(--bg-card);
      }
      select:focus, input[type="number"]:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(46, 125, 50, 0.1);
      }
      .citation {
        display: inline-block;
        background: var(--primary);
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        margin: 0 2px;
      }
      .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: var(--text-muted);
      }
      .empty-icon {
        font-size: 48px;
        margin-bottom: 16px;
        opacity: 0.3;
      }
      .loading-text {
        text-align: center;
        color: var(--text-muted);
        margin-top: 12px;
      }
    </style>
  </head>
  <body>
    <div class="nav">
      <a href="/ui/checks" class="btn">← Verificaciones</a>
      <a href="/ui/library" class="btn">Biblioteca</a>
    </div>
    
    <h1>Consultas RAG - Sistema de Búsqueda Inteligente</h1>
    <div class="muted" style="margin-bottom: 20px">
      Realiza preguntas en lenguaje natural sobre agricultura. El sistema busca en documentos indexados y genera respuestas precisas con referencias.
    </div>

    <div class="info-box">
      <strong>¿Cómo funciona?</strong> El sistema RAG (Retrieval-Augmented Generation) combina búsqueda híbrida (BM25 + embeddings semánticos) 
      para encontrar fragmentos relevantes y luego genera una respuesta coherente usando IA. Las respuestas incluyen citaciones a los documentos fuente.
    </div>

    <div class="card">
      <div class="card-header">Realizar Consulta</div>
      
      <div class="search-box">
        <input 
          type="text" 
          id="queryInput" 
          class="search-input" 
          placeholder="Ej: ¿Cómo fertilizar maíz en etapa vegetativa?" 
          autocomplete="off"
        />
      </div>

      <details style="margin-bottom: 16px">
        <summary style="cursor: pointer; font-weight: 600; color: var(--primary); margin-bottom: 8px">
          Configuración avanzada
        </summary>
        <div class="settings-grid">
          <div class="setting-item">
            <label class="setting-label">Modo de búsqueda</label>
            <select id="modeSelect">
              <option value="hybrid">Híbrido (BM25 + Embeddings)</option>
              <option value="bm25">Solo BM25 (palabras clave)</option>
              <option value="vector">Solo Vector (semántico)</option>
            </select>
          </div>
          <div class="setting-item">
            <label class="setting-label">Fragmentos a recuperar</label>
            <input type="number" id="kInput" value="5" min="1" max="20" />
          </div>
          <div class="setting-item">
            <label class="setting-label">Ámbito</label>
            <select id="scopeSelect">
              <option value="global">Toda la biblioteca (puede mezclar cultivos)</option>
              <option value="crop_boost">Priorizar cultivo seleccionado</option>
              <option value="crop_strict">Solo alineado al cultivo (estricto)</option>
            </select>
          </div>
          <div class="setting-item">
            <label class="setting-label">Priorizar cultivo (desde catálogo)</label>
            <select id="cropSelect"><option value="">— Ninguno —</option></select>
          </div>
          <div class="setting-item">
            <label class="setting-label">Etiquetas BM25 (opcional)</label>
            <input type="text" id="labelsInput" placeholder="RECOMENDACION, DATO" />
          </div>
        </div>
        <p class="muted" style="margin-top:8px">
          Si no eliges cultivo o dejas «toda la biblioteca», el sistema puede mezclar fuentes de varios cultivos (comportamiento por defecto).
          Con cultivo + «priorizar» o «estricto», la recuperación favorece documentación de ese cultivo.
        </p>
      </details>

      <button class="btn btn-primary" id="searchBtn" style="width: 100%">
        Buscar Respuesta
      </button>
    </div>

    <div id="resultsContainer"></div>

    <script>
      const API_BASE = '';
      let isSearching = false;

      function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
      }

      function renderLoading() {
        return \`
          <div class="card">
            <div style="text-align: center; padding: 40px 20px">
              <div class="spinner"></div>
              <div class="loading-text">Buscando en la base de conocimiento...</div>
              <div class="muted" style="margin-top: 8px">Analizando documentos con IA</div>
            </div>
          </div>
        \`;
      }

      function renderAnswer(data) {
        let html = '';
        
        if (data.answer) {
          html += \`
            <div class="answer-box">
              <div class="answer-title">
                <span>Respuesta Generada</span>
              </div>
              <div class="answer-text">\${escapeHtml(data.answer)}</div>
              \${data.citations && data.citations.length > 0 ? 
                \`<div class="muted" style="margin-top: 12px">
                  <strong>Fuentes:</strong> \${data.citations.map((c, i) => 
                    \`<span class="citation">[\${i+1}]</span> \${escapeHtml(c)}\`
                  ).join(' ')}
                </div>\` : ''}
              <div class="muted" style="margin-top: 8px; font-size: 12px">
                Modo: <strong>\${data.answer_mode || 'desconocido'}</strong>
              </div>
            </div>
          \`;
        }

        html += \`<div class="card"><div class="card-header">Fragmentos Relevantes (\${data.total_retrieved})</div>\`;

        if (data.fragments && data.fragments.length > 0) {
          data.fragments.forEach((frag, i) => {
            const score = ((frag.score || 0) * 100).toFixed(1);
            const text = frag.text || '';
            const preview = text.length > 400 ? text.substring(0, 400) + '...' : text;
            
            html += \`
              <div class="fragment-card">
                <div class="fragment-header">
                  <div class="fragment-title">Fragmento \${i + 1}</div>
                  <span class="badge badge-success">\${score}% relevancia</span>
                </div>
                <div class="fragment-text">\${escapeHtml(preview)}</div>
                <div class="fragment-meta">
                  <div class="meta-item">
                    <span>\${escapeHtml(frag.doc_title || frag.doc_id?.substring(0, 16) || 'Documento')}</span>
                  </div>
                  \${frag.page_start ? \`
                    <div class="meta-item">
                      <span>Página \${frag.page_start}</span>
                    </div>
                  \` : ''}
                  <div class="meta-item">
                    <span>ID: \${escapeHtml((frag.doc_id || '').substring(0, 8))}</span>
                  </div>
                </div>
              </div>
            \`;
          });
        } else {
          html += \`
            <div class="empty-state">
              <div>No se encontraron fragmentos relevantes</div>
              <div class="muted" style="margin-top: 8px">Intenta reformular tu pregunta o usar términos diferentes</div>
            </div>
          \`;
        }

        html += '</div>';
        return html;
      }

      function renderError(message) {
        return \`
          <div class="card" style="border-left: 4px solid #dc2626">
            <div class="card-header" style="color: #dc2626">Error en la consulta</div>
            <div style="color: var(--text)">\${escapeHtml(message)}</div>
            <div class="muted" style="margin-top: 8px">Verifica que el backend esté disponible y los índices estén construidos.</div>
          </div>
        \`;
      }

      async function loadKnownCrops() {
        try {
          const r = await fetch('/ai/api/known-crops');
          const list = await r.json();
          const sel = document.getElementById('cropSelect');
          if (!sel || !Array.isArray(list)) return;
          for (let i = sel.options.length - 1; i >= 1; i--) sel.remove(i);
          list.forEach((item) => {
            const name = item && item.crop_name;
            if (!name) return;
            const o = document.createElement('option');
            o.value = name;
            o.textContent = name;
            sel.appendChild(o);
          });
        } catch (e) {
          console.warn('No se pudo cargar /ai/api/known-crops', e);
        }
      }

      async function executeSearch() {
        if (isSearching) return;
        
        const query = document.getElementById('queryInput').value.trim();
        if (!query) {
          alert('Por favor ingresa una pregunta');
          return;
        }

        isSearching = true;
        const btn = document.getElementById('searchBtn');
        const originalText = btn.textContent;
        btn.textContent = 'Buscando...';
        btn.disabled = true;

        const container = document.getElementById('resultsContainer');
        container.innerHTML = renderLoading();

        try {
          const modeUi = document.getElementById('modeSelect').value;
          const mode = modeUi === 'bm25' ? 'lex' : modeUi === 'vector' ? 'dense' : 'hybrid';
          const k = parseInt(document.getElementById('kInput').value) || 5;
          const scopeEl = document.getElementById('scopeSelect');
          const cropEl = document.getElementById('cropSelect');
          const labelsEl = document.getElementById('labelsInput');
          const retrieval_scope = scopeEl ? scopeEl.value : 'global';
          const crop_focus = cropEl && cropEl.value ? String(cropEl.value).trim() : '';
          const labelsRaw = labelsEl ? String(labelsEl.value || '').trim() : '';
          const labels_filter = labelsRaw
            ? labelsRaw.split(',').map((s) => s.trim()).filter(Boolean)
            : undefined;

          const payload = /** @type {Record<string, unknown>} */ ({ query, k, mode });
          if (labels_filter && labels_filter.length) payload.labels_filter = labels_filter;
          if (crop_focus && retrieval_scope !== 'global') {
            payload.crop_focus = crop_focus;
            payload.retrieval_scope = retrieval_scope;
          }

          const response = await fetch('/ai/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });

          if (!response.ok) {
            throw new Error(\`HTTP \${response.status}: \${response.statusText}\`);
          }

          const data = await response.json();
          container.innerHTML = renderAnswer(data);
        } catch (error) {
          container.innerHTML = renderError(error.message);
        } finally {
          isSearching = false;
          btn.textContent = originalText;
          btn.disabled = false;
        }
      }

      document.getElementById('searchBtn').addEventListener('click', executeSearch);
      document.getElementById('queryInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') executeSearch();
      });

      loadKnownCrops();

      // Ejemplos rápidos
      const examples = [
        '¿Cómo fertilizar maíz en etapa vegetativa?',
        'Plagas comunes del jitomate',
        'Variedades de frijol resistentes a sequía',
        'Calendario de siembra para clima templado'
      ];
      
      console.log('Ejemplos de consultas:', examples);
    </script>
  </body>
  </html>`;
    rep.header('Content-Type', 'text/html; charset=utf-8');
    return page;
});
// Estado de ejecución
app.get('/runtime/status', async (_req, rep) => {
    const stats = scheduler.stats;
    const circuitState = circuit.stats?.state ?? 'closed';
    const payload = {
        en_cola: stats.queued,
        en_vuelo: stats.inFlight,
        circuito: circuitState,
        modo_degradado: circuitState !== 'closed',
        capacidad: { max_concurrency: stats.maxConcurrency, queue_capacity: stats.queueCapacity },
    };
    return payload;
});
// ─────────────────────────────────────────────────────────────────────────────
// Panel de Ingesta de Datos (Excel → BD)
// Ruta: /ui/ingesta
// ─────────────────────────────────────────────────────────────────────────────
app.get('/ui/ingesta', async (_req, rep) => {
    const FRONTEND = 'http://localhost:4000';
    const html = `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MILPA · Ingesta de Datos</title>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"><\/script>
<style>
:root {
  --primary: #2E7D32;
  --primary-dk: #1b5e20;
  --primary-lt: #e8f5e9;
  --accent: #f59e0b;
  --accent-lt: #fef3c7;
  --bg: #f4f6f9;
  --surface: #ffffff;
  --border: #e2e8f0;
  --text: #111827;
  --muted: #6b7280;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,.08);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
a { color: var(--primary); }

/* Topbar */
.topbar {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 28px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: var(--shadow);
}
.topbar-brand { font-size: 15px; font-weight: 700; color: var(--primary); letter-spacing: .04em; text-decoration: none; }
.topbar-nav { display: flex; gap: 4px; }
.topbar-nav a {
  font-size: 13px; font-weight: 500; color: var(--muted); text-decoration: none;
  padding: 6px 12px; border-radius: 6px; transition: all .15s;
}
.topbar-nav a:hover { color: var(--text); background: #f1f5f9; }
.topbar-nav a.back {
  color: var(--primary); border: 1px solid var(--border);
}
.topbar-nav a.back:hover { background: var(--primary-lt); }

/* Layout */
.page { max-width: 1280px; margin: 0 auto; padding: 28px 28px 48px; }
.page-header { margin-bottom: 28px; }
.page-header h1 { font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.page-header .sub { font-size: 14px; color: var(--muted); }

.layout { display: grid; grid-template-columns: 1fr 380px; gap: 24px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }

/* Cards */
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow);
  margin-bottom: 20px; overflow: hidden;
}
.card-head {
  padding: 14px 18px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px;
}
.card-head .step {
  width: 24px; height: 24px; border-radius: 50%;
  background: var(--primary); color: #fff;
  font-size: 12px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.card-head h2 { font-size: 14px; font-weight: 600; color: var(--text); }
.card-head .tag {
  margin-left: auto; font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: .04em;
}
.tag-green { background: var(--primary-lt); color: var(--primary); }
.tag-amber { background: var(--accent-lt); color: #92400e; }
.card-body { padding: 18px; }

/* Drop zone */
.drop-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 36px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color .2s, background .2s;
  background: #fafbfc;
}
.drop-zone:hover, .drop-zone.over {
  border-color: var(--primary);
  background: var(--primary-lt);
}
.drop-icon {
  width: 48px; height: 48px; margin: 0 auto 12px;
  background: var(--primary-lt); border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
}
.drop-icon svg { width: 24px; height: 24px; stroke: var(--primary); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.drop-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.drop-hint { font-size: 12px; color: var(--muted); }

/* Tabs */
.tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 14px; }
.tab-btn {
  padding: 8px 14px; font-size: 13px; font-weight: 500; color: var(--muted);
  border: none; background: none; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  transition: color .15s, border-color .15s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }

/* Badge counts */
.badges { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.badge {
  font-size: 11px; font-weight: 600; padding: 3px 10px;
  border-radius: 20px; border: 1px solid;
}
.badge-g { color: #166534; background: #dcfce7; border-color: #bbf7d0; }
.badge-b { color: #1e40af; background: #dbeafe; border-color: #bfdbfe; }
.badge-a { color: #92400e; background: #fef3c7; border-color: #fde68a; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all .15s; text-decoration: none; border: 1px solid transparent;
}
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-dk); }
.btn-secondary { background: var(--surface); color: var(--text); border-color: var(--border); }
.btn-secondary:hover { background: #f1f5f9; }
.btn-amber { background: var(--accent); color: #fff; }
.btn-amber:hover { background: #d97706; }
.btn-full { width: 100%; }
.btn:disabled { opacity: .5; cursor: not-allowed; }

/* Form controls */
label.field-label { display: block; font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
select, input[type=number], input[type=text] {
  width: 100%; padding: 7px 10px; border: 1px solid var(--border);
  border-radius: 6px; font-size: 13px; font-family: inherit;
  background: var(--surface); color: var(--text);
  transition: border-color .15s, box-shadow .15s;
}
select:focus, input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(46,125,50,.12); }
.checkbox-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
.checkbox-row input { width: auto; }

/* Preview table */
.preview-wrap { max-height: 280px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
.preview-wrap table { width: 100%; border-collapse: collapse; }
.preview-wrap th { background: #f8fafc; padding: 6px 10px; text-align: left; font-weight: 600; border-bottom: 1px solid var(--border); white-space: nowrap; position: sticky; top: 0; }
.preview-wrap td { padding: 5px 10px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.preview-wrap tr:last-child td { border-bottom: none; }

/* Log box */
.log-box {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 12px; line-height: 1.6;
  background: #0f172a; color: #94a3b8;
  border-radius: 6px; padding: 12px 14px;
  min-height: 72px; max-height: 180px; overflow-y: auto;
}
.log-ok { color: #4ade80; }
.log-err { color: #f87171; }
.log-info { color: #60a5fa; }
.log-ts { color: #475569; font-size: 11px; }

/* Schema box */
.schema-box {
  background: #f8fafc; border: 1px solid var(--border);
  border-radius: 6px; padding: 12px 14px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 11.5px; white-space: pre; overflow-x: auto;
  color: var(--text); line-height: 1.7;
}

/* Users table */
.users-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.users-table th { padding: 8px 12px; background: #f8fafc; text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); border-bottom: 1px solid var(--border); }
.users-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }
.users-table tr:last-child td { border-bottom: none; }

/* Frontend links */
.links-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--primary-lt); border: 1px solid #c6e6c7;
  border-radius: var(--radius); padding: 12px 16px; margin-bottom: 24px;
  font-size: 13px;
}
.links-bar .links-label { font-weight: 600; color: var(--primary-dk); margin-right: 4px; }

/* Fieldset */
.field-group { display: grid; gap: 12px; }
.field-group.cols-2 { grid-template-columns: 1fr 1fr; }
@media (max-width: 520px) { .field-group.cols-2 { grid-template-columns: 1fr; } }

.info-msg { font-size: 12px; color: var(--muted); margin-top: 4px; }
.divider { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
.text-muted { color: var(--muted); font-size: 13px; }
#bootstrapResult { margin-top: 12px; font-size: 13px; min-height: 20px; }
.result-ok { color: #166534; font-weight: 500; }
.result-err { color: #991b1b; font-weight: 500; }
#fileInfo { font-size: 12px; color: var(--muted); margin-top: 8px; min-height: 18px; }
.dataset-live-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 10px; }
.ds-pre { font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 11px; background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 10px; max-height: 140px; overflow: auto; white-space: pre-wrap; word-break: break-word; margin-top: 8px; }
.ds-hint { font-size: 11px; color: var(--muted); margin-bottom: 10px; line-height: 1.45; }
.ds-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
.ds-status { font-size: 12px; margin-top: 8px; min-height: 18px; }
.ds-status.ok { color: #166534; }
.ds-status.err { color: #991b1b; }
</style>
</head>
<body>

<header class="topbar">
  <a href="/ui/checks" class="topbar-brand">MILPA AI</a>
  <nav class="topbar-nav">
    <a href="/ui/library">Biblioteca</a>
    <a href="/ui/query">Consultas RAG</a>
    <a href="/ui/checks" class="back">Verificaciones</a>
  </nav>
</header>

<main class="page">
  <div class="page-header">
    <h1>Ingesta de datos</h1>
    <div class="sub">Carga cultivos, lecturas de sensores y datos globales desde un archivo Excel, o genera un dataset sintetico de prueba.</div>
  </div>

  <!-- Links frontend -->
  <div class="links-bar">
    <span class="links-label">Vista en el frontend:</span>
    <a href="${FRONTEND}/datos.html" target="_blank" class="btn btn-secondary">Datos</a>
    <a href="${FRONTEND}/tiempo-real.html" target="_blank" class="btn btn-secondary">Tiempo real</a>
    <a href="${FRONTEND}/login.html" target="_blank" class="btn btn-secondary">Login</a>
  </div>

  <!-- Autenticacion frontend (token en localStorage de :8080) -->
  <div class="card">
    <div class="card-head"><h2>Autenticacion frontend</h2></div>
    <div class="card-body">
      <div class="field-group cols-2" style="margin-bottom:12px">
        <div>
          <label class="field-label" for="authUser">Usuario</label>
          <input type="text" id="authUser" autocomplete="username" placeholder="usuario" />
        </div>
        <div>
          <label class="field-label" for="authPass">Contrasena</label>
          <input type="password" id="authPass" autocomplete="current-password" placeholder="••••••" />
        </div>
      </div>
      <div class="ds-actions" style="align-items:center; gap:10px">
        <button type="button" class="btn btn-primary" id="btnAuthLogin">Login y guardar token</button>
        <button type="button" class="btn btn-secondary" id="btnAuthClear">Borrar token</button>
        <span id="authStatus" class="text-muted"></span>
      </div>
      <div class="info-msg">Este token se guarda en localStorage del origen :8080.</div>
    </div>
  </div>

  <!-- Panel dataset en vivo (misma BD SQLite que el backend :8000 vía proxy /ai) -->
  <div class="card" id="datasetLiveCard">
    <div class="card-head">
      <span class="step">●</span>
      <h2>Dataset en vivo (escritura directa)</h2>
      <span class="tag tag-green">SQLite</span>
    </div>
    <div class="card-body">
      <p class="ds-hint">
        Una sola acción aplicada a la vez: INSERT real en <code>sensor_readings</code> (parcela visible en Datos / Tiempo real) y UPDATE del registro vigente en <code>edaphology_global_readings</code>
        si no marca «solo parcela». Cada pulsación solicita confirmación; no hay «deshacer» — conserve copia del <code>.db</code> ante pruebas fuertes.
        <strong>Entorno local</strong>: rutas proxificadas desde el presenter sin autenticación.
      </p>
      <div class="ds-actions" style="flex-wrap:wrap; align-items:flex-end; gap:12px;">
        <div>
          <label class="field-label" for="dsUserId">Usuario (parcela)</label>
          <select id="dsUserId" style="min-width:220px; padding:8px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px; background:var(--surface); color:var(--text);">
            <option value="">Cargando usuarios…</option>
          </select>
        </div>
        <button type="button" class="btn btn-secondary" id="dsBtnRefresh">Actualizar vista (JSON)</button>
      </div>
      <pre class="ds-pre" id="dsSnapshotJson">// Elige usuario y pulsa «Actualizar vista»…</pre>

      <div class="dataset-live-grid">
        <div class="card" style="margin:0; box-shadow:none; grid-column: 1 / -1;">
          <div class="card-head" style="padding:10px 14px"><h2 style="font-size:13px">Parcela — sensores en vivo + predio global</h2></div>
          <div class="card-body" style="padding:12px 14px">
            <p id="dsStateMeta" class="ds-hint" style="margin-bottom:10px"></p>
            <div class="field-group cols-2">
              <div><label class="field-label">Ubicación</label><input type="text" id="dsLoc" placeholder="general"/></div>
              <div><label class="field-label">Temp. suelo °C</label><input type="number" id="dsSoilTemp" step="0.1"/></div>
              <div><label class="field-label">Humedad suelo %</label><input type="number" id="dsSm" step="0.1"/></div>
              <div><label class="field-label">Temp. aire °C</label><input type="number" id="dsTa" step="0.1"/></div>
              <div><label class="field-label">Humedad aire %</label><input type="number" id="dsHa" step="0.1"/></div>
              <div><label class="field-label">Luz % (solo parcela)</label><input type="number" id="dsLi" step="0.1"/></div>
              <div><label class="field-label">Precip. mm</label><input type="number" id="dsPr" step="0.1"/></div>
              <div><label class="field-label">Viento km/h</label><input type="number" id="dsWs" step="0.1"/></div>
              <div><label class="field-label">pH</label><input type="number" id="dsPh" step="0.1"/></div>
              <div><label class="field-label">Conductividad</label><input type="number" id="dsEc" step="0.1"/></div>
              <div style="grid-column:1/-1"><label class="field-label">Notas (predio global)</label><input type="text" id="dsNotes" placeholder="Observaciones"/></div>
            </div>
            <label class="checkbox-row" style="margin:14px 0 10px">
              <input type="checkbox" id="dsParcelOnly"/>
              Solo escritura parcela (<code>sensor_readings</code>). No actualizar predio global.
            </label>
            <label class="checkbox-row" style="margin:0 0 12px">
              <input type="checkbox" id="dsOneCrop"/>
              Solo un cultivo activo:
              <select id="dsCropSelect" style="max-width:220px;margin-left:8px"><option value="">— cargar vista —</option></select>
            </label>
            <button type="button" class="btn btn-primary btn-full" id="dsBtnApply">Aplicar a la base de datos</button>
          </div>
        </div>
        <div class="card" style="margin:0; box-shadow:none; grid-column: 1 / -1;">
          <div class="card-head" style="padding:10px 14px"><h2 style="font-size:13px">Perfil agronómico (<code>crop_profiles</code>)</h2></div>
          <div class="card-body" style="padding:12px 14px">
            <div class="ds-actions">
              <select id="dsProfileCrop" style="max-width:260px"><option value="">— cultivos —</option></select>
              <button type="button" class="btn btn-secondary" id="dsBtnLoadProfile">Cargar perfil</button>
              <button type="button" class="btn btn-primary" id="dsBtnSaveProfile">Guardar cambios</button>
            </div>
            <div class="field-group cols-2">
              <div><label class="field-label">cycle_days</label><input type="number" id="dsPfCd" min="15" max="400"/></div>
              <div><label class="field-label">Variedad</label><input type="text" id="dsPfVar"/></div>
              <div><label class="field-label">Temp. min °C</label><input type="number" id="dsPfTmin" step="0.1"/></div>
              <div><label class="field-label">Temp. max °C</label><input type="number" id="dsPfTmax" step="0.1"/></div>
              <div><label class="field-label">Hum. suelo min %</label><input type="number" id="dsPfSmin" step="0.1"/></div>
              <div><label class="field-label">Hum. suelo max %</label><input type="number" id="dsPfSmax" step="0.1"/></div>
              <div><label class="field-label">Hum. aire min %</label><input type="number" id="dsPfHmin" step="0.1"/></div>
              <div><label class="field-label">Hum. aire max %</label><input type="number" id="dsPfHmax" step="0.1"/></div>
              <div><label class="field-label">pH min</label><input type="number" id="dsPfPhMin" step="0.1"/></div>
              <div><label class="field-label">pH max</label><input type="number" id="dsPfPhMax" step="0.1"/></div>
              <div style="grid-column:1/-1"><label class="field-label">Notas</label><input type="text" id="dsPfNotes"/></div>
            </div>
          </div>
        </div>
      </div>
      <div class="ds-status" id="dsStatus"></div>
    </div>
  </div>

  <div class="layout">

    <!-- Columna principal -->
    <div>

      <!-- Paso 1: Drop zone -->
      <div class="card">
        <div class="card-head">
          <span class="step">1</span>
          <h2>Carga tu archivo Excel</h2>
          <span class="tag tag-green">xlsx / xls</span>
        </div>
        <div class="card-body">
          <div class="drop-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
            <div class="drop-icon">
              <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            </div>
            <div class="drop-title">Arrastra tu archivo .xlsx aqui o haz clic para seleccionar</div>
            <div class="drop-hint">Requiere hojas: cultivos &middot; sensores &middot; global</div>
          </div>
          <input type="file" id="fileInput" accept=".xlsx,.xls" style="display:none"/>
          <div id="fileInfo"></div>
        </div>
      </div>

      <!-- Paso 2: Preview -->
      <div class="card" id="previewCard" style="display:none">
        <div class="card-head">
          <span class="step">2</span>
          <h2>Vista previa</h2>
        </div>
        <div class="card-body">
          <div class="tabs">
            <button class="tab-btn active" data-tab="cultivos">Cultivos</button>
            <button class="tab-btn" data-tab="sensores">Sensores</button>
            <button class="tab-btn" data-tab="nutrientes">Nutrientes</button>
            <button class="tab-btn" data-tab="riego">Riego</button>
            <button class="tab-btn" data-tab="global">Global</button>
          </div>
          <div id="previewContent" class="preview-wrap"></div>
          <div class="badges">
            <span class="badge badge-g" id="badgeCultivos">0 cultivos</span>
            <span class="badge badge-b" id="badgeSensores">0 lecturas</span>
            <span class="badge badge-y" id="badgeNutrientes">0 análisis</span>
            <span class="badge badge-r" id="badgeRiego">0 riegos</span>
            <span class="badge badge-a" id="badgeGlobal">0 globales</span>
          </div>
        </div>
      </div>

      <!-- Paso 3: Importar -->
      <div class="card" id="sendCard" style="display:none">
        <div class="card-head">
          <span class="step">3</span>
          <h2>Importar al sistema</h2>
        </div>
        <div class="card-body">
          <div class="field-group cols-2" style="margin-bottom:14px">
            <div>
              <label class="field-label">Usuario destino</label>
              <select id="targetUserId"><option value="">Cargando...</option></select>
            </div>
            <div style="display:flex;align-items:flex-end">
              <label class="checkbox-row">
                <input type="checkbox" id="clearExisting"/>
                Limpiar datos existentes
              </label>
            </div>
          </div>
          <button class="btn btn-primary btn-full" id="btnImport">Importar datos</button>
          <hr class="divider"/>
          <div class="log-box" id="logBox">// Los resultados apareceran aqui...</div>
        </div>
      </div>

    </div>

    <!-- Columna lateral -->
    <div>

      <!-- Dataset sintetico -->
      <div class="card">
        <div class="card-head">
          <h2>Dataset sintetico</h2>
          <span class="tag tag-amber">Prueba</span>
        </div>
        <div class="card-body">
          <p class="text-muted" style="margin-bottom:14px">Genera y carga automaticamente un dataset realista con cultivos, lecturas de sensores semanales y datos globales edafologicos.</p>
          <div class="field-group cols-2" style="margin-bottom:12px">
            <div>
              <label class="field-label">Usuario destino</label>
              <select id="bootstrapUserId"><option value="">Cargando...</option></select>
            </div>
            <div>
              <label class="field-label">Semanas de historial</label>
              <input type="number" id="bootstrapWeeks" value="24" min="4" max="104"/>
            </div>
          </div>
          <label class="checkbox-row" style="margin-bottom:14px">
            <input type="checkbox" id="bootstrapClear" checked/>
            Limpiar datos existentes del usuario
          </label>
          <button class="btn btn-amber btn-full" id="btnBootstrap">Generar y cargar dataset</button>
          <div id="bootstrapResult"></div>
        </div>
      </div>

      <!-- Formato Excel -->
      <div class="card">
        <div class="card-head">
          <h2>Formato esperado del Excel</h2>
        </div>
        <div class="card-body" style="padding:12px">
          <div class="tabs">
            <button class="tab-btn active" data-schema="cultivos">cultivos</button>
            <button class="tab-btn" data-schema="sensores">sensores</button>
            <button class="tab-btn" data-schema="nutrientes">nutrientes</button>
            <button class="tab-btn" data-schema="riego">riego</button>
            <button class="tab-btn" data-schema="global">global</button>
          </div>
          <div class="schema-box" id="schemaContent"></div>
        </div>
      </div>

      <!-- Usuarios registrados -->
      <div class="card">
        <div class="card-head"><h2>Usuarios registrados</h2></div>
        <div style="overflow:auto">
          <table class="users-table" id="usersTable">
            <thead><tr><th>ID</th><th>Usuario</th><th>Cultivos</th><th>Lecturas</th></tr></thead>
            <tbody><tr><td colspan="4" class="text-muted" style="padding:14px;text-align:center">Cargando...</td></tr></tbody>
          </table>
        </div>
      </div>

    </div>
  </div>
</main>

<script>
// ─── Config ───────────────────────────────────────────────────────────────────
const FRONTEND = '${FRONTEND}';
const AUTH_STORAGE_KEY = 'token';
let parsedDataset = null;
let activePreviewTab = 'cultivos';

function getAuthToken() {
  return localStorage.getItem(AUTH_STORAGE_KEY) || sessionStorage.getItem(AUTH_STORAGE_KEY) || '';
}

function setAuthToken(token) {
  if (!token) return;
  localStorage.setItem(AUTH_STORAGE_KEY, token);
}

function clearAuthToken() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

function authTokenPreview(token) {
  if (!token) return 'Sin token cargado.';
  if (token.length <= 12) return 'Token activo.';
  return 'Token activo: ' + token.slice(0, 6) + '...' + token.slice(-4);
}

function renderAuthStatus(msg, isError) {
  const el = document.getElementById('authStatus');
  if (!el) return;
  const token = getAuthToken();
  const base = msg || authTokenPreview(token);
  el.textContent = base;
  el.className = 'text-muted' + (isError ? ' result-err' : '');
}

async function authLogin() {
  const user = (document.getElementById('authUser') || {}).value || '';
  const pass = (document.getElementById('authPass') || {}).value || '';
  if (!user || !pass) { renderAuthStatus('Usuario y contrasena requeridos.', true); return; }
  renderAuthStatus('Iniciando sesion...', false);
  try {
    const r = await fetch(FRONTEND + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ username: String(user).trim(), password: String(pass) }),
    });
    const data = await r.json();
    if (!r.ok || !data?.token) {
      renderAuthStatus('Login fallido: ' + (data?.error || r.status), true);
      return;
    }
    setAuthToken(String(data.token));
    renderAuthStatus('Sesion lista para importar datasets.', false);
  } catch (e) {
    renderAuthStatus('Error de conexion: ' + e.message, true);
  }
}

const btnAuthLogin = document.getElementById('btnAuthLogin');
if (btnAuthLogin) btnAuthLogin.addEventListener('click', authLogin);
const btnAuthClear = document.getElementById('btnAuthClear');
if (btnAuthClear) btnAuthClear.addEventListener('click', () => {
  clearAuthToken();
  renderAuthStatus('Token eliminado.', false);
});
renderAuthStatus();

// ─── Schemas de columnas ─────────────────────────────────────────────────────
const SCHEMAS = {
  cultivos: \`Hoja: cultivos
Columna            Tipo      Ejemplo
───────────────────────────────────────
crop_name          texto     maiz
variety            texto     Criollo
planted_at         fecha     2026-01-15
expected_harvest_at fecha    2026-05-20
growth_stage       texto     desarrollo
status             texto     activo
progress           número    65
notes              texto     Lote norte\`,
  sensores: \`Hoja: sensores
Columna       Tipo      Rango       Ejemplo
──────────────────────────────────────────────
crop_name     texto               maiz
soil_moisture número    0-100%    64.5
air_temp      número    °C        26.3
air_humidity  número    0-100%    55.0
light         número    0-100%    78.2
precipitation número    mm        0.0
wind_speed    número    km/h      12.5
created_at    fecha/hora          2026-02-01 12:00:00\`,
  nutrientes: \`Hoja: nutrientes
Columna             Tipo      Rango     Ejemplo
────────────────────────────────────────────────
crop_name           texto               maiz
nitrogen            número    %         2.8
phosphorus          número    %         1.5
potassium           número    %         3.1
nitrogen_opt_min    número    %         3.0
nitrogen_opt_max    número    %         4.0
phosphorus_opt_min  número    %         2.0
phosphorus_opt_max  número    %         3.0
potassium_opt_min   número    %         2.5
potassium_opt_max   número    %         3.5
notes               texto               Análisis mensual
created_at          fecha/hora          2026-04-01 09:00:00\`,
  global: \`Hoja: global
Columna       Tipo      Rango       Ejemplo
──────────────────────────────────────────────
location_name texto               Región Norte
soil_temp     número    °C        18.5
air_temp      número    °C        24.0
air_humidity  número    0-100%    52.0
soil_moisture número    0-100%    46.3
precipitation número    mm        8.2
wind_speed    número    km/h      9.0
ph            número    0-14      6.8
conductivity  número    dS/m      1.1
notes         texto               Lectura semanal
created_at    fecha/hora          2026-02-01 12:00:00\`
};

function log(msg, cls='') {
  const box = document.getElementById('logBox');
  const ts = new Date().toLocaleTimeString();
  box.innerHTML += \`<div><span class="log-ts">[\${ts}]</span> <span class="\${cls}">\${msg}</span></div>\`;
  box.scrollTop = box.scrollHeight;
}

function bLog(msg, ok) {
  const box = document.getElementById('bootstrapResult');
  box.innerHTML = \`<span class="\${ok ? 'result-ok' : 'result-err'}">\${msg}</span>\`;
}

// ─── Usuarios ────────────────────────────────────────────────────────────────
async function loadUsers() {
  try {
    const r = await fetch('/api/admin/users');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const users = await r.json();
    const opts = users.map(u => \`<option value="\${u.id}">\${u.username} (ID \${u.id})</option>\`).join('');
    document.getElementById('targetUserId').innerHTML = opts;
    document.getElementById('bootstrapUserId').innerHTML = opts;
    const dsU = document.getElementById('dsUserId');
    if (dsU) dsU.innerHTML = opts || '<option value="">Sin usuarios</option>';
    const tbody = document.querySelector('#usersTable tbody');
    tbody.innerHTML = users.map(u => \`<tr>
      <td>\${u.id}</td><td><strong>\${u.username}</strong></td>
      <td>\${u.crop_count}</td><td>\${u.sensor_readings_count}</td>
    </tr>\`).join('') || '<tr><td colspan="4" class="text-muted text-center">Sin usuarios</td></tr>';
  } catch(e) {
    const fallback = '<option value="1">testuser (ID 1)</option>';
    document.getElementById('targetUserId').innerHTML = fallback;
    document.getElementById('bootstrapUserId').innerHTML = fallback;
    const dsU = document.getElementById('dsUserId');
    if (dsU) dsU.innerHTML = fallback;
    document.querySelector('#usersTable tbody').innerHTML = \`<tr><td colspan="4" class="text-warning text-center">\${e.message}</td></tr>\`;
  }
}

// ─── Schema tabs ─────────────────────────────────────────────────────────────
function renderSchema(key) {
  document.getElementById('schemaContent').textContent = SCHEMAS[key];
  document.querySelectorAll('[data-schema]').forEach(b => {
    b.classList.toggle('active', b.dataset.schema === key);
  });
}
document.querySelectorAll('[data-schema]').forEach(b => b.addEventListener('click', () => renderSchema(b.dataset.schema)));
renderSchema('cultivos');

// ─── Preview tabs ─────────────────────────────────────────────────────────────
document.querySelectorAll('[data-tab]').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    activePreviewTab = b.dataset.tab;
    renderPreview();
  });
});

function renderPreview() {
  if (!parsedDataset) return;
  const key = activePreviewTab;
  const map = { cultivos: 'crops', sensores: 'sensor_readings', nutrientes: 'soil_nutrients', riego: 'irrigation_events', global: 'global_readings' };
  const rows = parsedDataset[map[key]] || [];
  if (!rows.length) { document.getElementById('previewContent').innerHTML = '<em class="text-muted">Sin datos para esta hoja.</em>'; return; }
  const cols = Object.keys(rows[0]);
  const head = '<tr>' + cols.map(c => \`<th>\${c}</th>\`).join('') + '</tr>';
  const body = rows.slice(0,20).map(r => '<tr>' + cols.map(c => \`<td>\${r[c] ?? ''}</td>\`).join('') + '</tr>').join('');
  document.getElementById('previewContent').innerHTML = \`<table class="table table-sm table-bordered">\${head}\${body}</table>\${rows.length>20?'<small class="text-muted">Mostrando 20 de '+rows.length+' filas.</small>':''}\`;
}

// ─── Drag & Drop / File Input ─────────────────────────────────────────────────
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('over'));
dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('over'); handleFile(e.dataTransfer.files[0]); });
fileInput.addEventListener('change', () => fileInput.files[0] && handleFile(fileInput.files[0]));

function handleFile(file) {
  if (!file) return;
  document.getElementById('fileInfo').textContent = 'Procesando: ' + file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)…';
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const wb = XLSX.read(e.target.result, { type:'array', cellDates:true });
      const crops         = sheetToJson(wb, 'cultivos');
      const sensorRows    = sheetToJson(wb, 'sensores');
      const nutrientRows  = sheetToJson(wb, 'nutrientes');
      const riegoRows     = sheetToJson(wb, 'riego');
      const globalRows    = sheetToJson(wb, 'global');
      parsedDataset = {
        crops: crops.map(r => ({
          crop_name:           String(r.crop_name||'').toLowerCase().trim(),
          variety:             r.variety||null,
          planted_at:          fmtDate(r.planted_at),
          expected_harvest_at: fmtDate(r.expected_harvest_at)||null,
          growth_stage:        r.growth_stage||null,
          status:              r.status||'activo',
          progress:            Number(r.progress)||0,
          notes:               r.notes||null,
        })),
        sensor_readings: sensorRows.map(r => ({
          crop_name:     String(r.crop_name||'').toLowerCase().trim(),
          soil_moisture: Number(r.soil_moisture)||null,
          air_temp:      Number(r.air_temp)||null,
          air_humidity:  Number(r.air_humidity)||null,
          light:         Number(r.light)||null,
          precipitation: Number(r.precipitation)||0,
          wind_speed:    Number(r.wind_speed)||null,
          created_at:    fmtDate(r.created_at)||null,
        })),
        soil_nutrients: nutrientRows.map(r => ({
          crop_name:          String(r.crop_name||'').toLowerCase().trim(),
          nitrogen:           Number(r.nitrogen)||null,
          phosphorus:         Number(r.phosphorus)||null,
          potassium:          Number(r.potassium)||null,
          nitrogen_opt_min:   r.nitrogen_opt_min   != null ? Number(r.nitrogen_opt_min)   : 3.0,
          nitrogen_opt_max:   r.nitrogen_opt_max   != null ? Number(r.nitrogen_opt_max)   : 4.0,
          phosphorus_opt_min: r.phosphorus_opt_min != null ? Number(r.phosphorus_opt_min) : 2.0,
          phosphorus_opt_max: r.phosphorus_opt_max != null ? Number(r.phosphorus_opt_max) : 3.0,
          potassium_opt_min:  r.potassium_opt_min  != null ? Number(r.potassium_opt_min)  : 2.5,
          potassium_opt_max:  r.potassium_opt_max  != null ? Number(r.potassium_opt_max)  : 3.5,
          notes:              r.notes||null,
          created_at:         fmtDate(r.created_at)||null,
        })),
        irrigation_events: riegoRows.map(r => ({
          crop_name:            String(r.crop_name||'').toLowerCase().trim(),
          event_date:           fmtDate(r.event_date)||new Date().toISOString().slice(0,10),
          liters_applied:       Number(r.liters_applied)||0,
          duration_minutes:     r.duration_minutes != null ? Number(r.duration_minutes) : null,
          method:               r.method||'goteo',
          soil_moisture_before: r.soil_moisture_before != null ? Number(r.soil_moisture_before) : null,
          soil_moisture_after:  r.soil_moisture_after  != null ? Number(r.soil_moisture_after)  : null,
          notes:                r.notes||null,
          created_at:           fmtDate(r.created_at)||null,
        })),
        global_readings: globalRows.map(r => ({
          location_name: String(r.location_name||'general'),
          soil_temp:     Number(r.soil_temp)||null,
          air_temp:      Number(r.air_temp)||null,
          air_humidity:  Number(r.air_humidity)||null,
          soil_moisture: Number(r.soil_moisture)||null,
          precipitation: Number(r.precipitation)||0,
          wind_speed:    Number(r.wind_speed)||null,
          ph:            Number(r.ph)||null,
          conductivity:  Number(r.conductivity)||null,
          notes:         r.notes||null,
          created_at:    fmtDate(r.created_at)||null,
        })),
      };
      document.getElementById('badgeCultivos').textContent   = parsedDataset.crops.length + ' cultivos';
      document.getElementById('badgeSensores').textContent   = parsedDataset.sensor_readings.length + ' lecturas';
      document.getElementById('badgeNutrientes').textContent = parsedDataset.soil_nutrients.length + ' análisis';
      document.getElementById('badgeRiego').textContent      = parsedDataset.irrigation_events.length + ' riegos';
      document.getElementById('badgeGlobal').textContent     = parsedDataset.global_readings.length + ' globales';
      document.getElementById('fileInfo').textContent = 'Archivo cargado: ' + file.name;
      document.getElementById('previewCard').style.display = '';
      document.getElementById('sendCard').style.display = '';
      renderPreview();
    } catch(err) {
      document.getElementById('fileInfo').textContent = 'Error al procesar el archivo: ' + err.message;
    }
  };
  reader.readAsArrayBuffer(file);
}

function sheetToJson(wb, sheetName) {
  const sheet = wb.Sheets[sheetName] || wb.Sheets[sheetName.charAt(0).toUpperCase()+sheetName.slice(1)];
  if (!sheet) { console.warn('Hoja no encontrada:', sheetName); return []; }
  return XLSX.utils.sheet_to_json(sheet, { defval: null });
}

function fmtDate(v) {
  if (!v) return null;
  if (v instanceof Date) return v.toISOString().slice(0,19).replace('T',' ');
  if (typeof v === 'string') return v.trim();
  return String(v);
}

// ─── Importar dataset ─────────────────────────────────────────────────────────
document.getElementById('btnImport').addEventListener('click', async () => {
  if (!parsedDataset) { log('⚠️ Carga un archivo Excel primero.', '#f0ad4e'); return; }
  const userId   = document.getElementById('targetUserId').value;
  const clearOld = document.getElementById('clearExisting').checked;
  const token    = getAuthToken();
  if (!userId) { log('⚠️ Selecciona un usuario.', '#f0ad4e'); return; }
  if (!token) { log('⚠️ Inicia sesion en el panel de autenticacion primero.', '#f0ad4e'); return; }
  log('📤 Enviando dataset a ' + FRONTEND + ' (usuario ' + userId + ')…', '#9cdcfe');
  try {
    const r = await fetch(FRONTEND + '/api/datasets/import', {
      method: 'POST',
      headers: { 'Content-Type':'application/json', Authorization:'Bearer '+token },
      body: JSON.stringify({ target_user_id: Number(userId), clear_existing: clearOld, dataset: parsedDataset }),
    });
    const data = await r.json();
    if (!r.ok) { log('❌ Error: ' + (data.error||r.status), '#f47067'); return; }
    log(\`✅ Importado: \${data.summary?.created_crops||0} cultivos, \${data.summary?.inserted_sensor_readings||0} lecturas sensor, \${data.summary?.inserted_soil_nutrients||0} nutrientes, \${data.summary?.inserted_irrigation_events||0} riegos, \${data.summary?.inserted_global_readings||0} globales.\`, '#4ec9b0');
    loadUsers();
  } catch(e) { log('❌ ' + e.message, '#f47067'); }
});

// ─── Dataset sintético ────────────────────────────────────────────────────────
document.getElementById('btnBootstrap').addEventListener('click', async () => {
  const userId = document.getElementById('bootstrapUserId').value;
  const weeks  = Number(document.getElementById('bootstrapWeeks').value) || 24;
  const clear  = document.getElementById('bootstrapClear').checked;
  const token  = getAuthToken();
  if (!userId) { bLog('⚠️ Selecciona un usuario.'); return; }
  if (!token) { bLog('⚠️ Inicia sesion en el panel de autenticacion primero.'); return; }
  bLog('⏳ Generando dataset sintético…');
  try {
    const r = await fetch(FRONTEND + '/api/datasets/bootstrap', {
      method:'POST',
      headers:{ 'Content-Type':'application/json', Authorization:'Bearer '+token },
      body: JSON.stringify({ target_user_id: Number(userId), weeks, clear_existing: clear }),
    });
    const data = await r.json();
    if (!r.ok) { bLog('❌ ' + (data.error||r.status)); return; }
    bLog(\`✅ Dataset sintético cargado — \${data.summary?.created_crops||0} cultivos, \${data.summary?.inserted_sensor_readings||0} lecturas, \${data.summary?.inserted_global_readings||0} globales (\${weeks} semanas).\`);
    loadUsers();
  } catch(e) { bLog('❌ ' + e.message); }
});

// ─── Panel dataset en vivo (proxy /ai → backend :8000) ─────────────────────────
const DS_AI = '/ai';

/** Cada escritura pide confirmación; no hay deshacer. */
function dsConfirmRealWrite(what) {
  return window.confirm(
    'CONFIRMAR ESCRITURA EN SQLITE\\n\\n' +
    what +
    '\\n\\n¿Continuar?'
  );
}

function dsSetStatus(msg, ok) {
  const el = document.getElementById('dsStatus');
  el.textContent = msg;
  el.className = 'ds-status ' + (ok === undefined ? '' : (ok ? 'ok' : 'err'));
}

function dsNum(id) {
  const el = document.getElementById(id);
  if (!el) return undefined;
  const v = String(el.value || '').trim();
  if (v === '') return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function dsClearUnifiedInputs() {
  ['dsLoc','dsSoilTemp','dsSm','dsTa','dsHa','dsLi','dsPr','dsWs','dsPh','dsEc','dsNotes'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
}

function dsFillField(id, val) {
  const el = document.getElementById(id);
  if (el && val != null) el.value = val;
}

async function dsRefreshSnapshot() {
  const uidEl = document.getElementById('dsUserId');
  const uid = uidEl ? uidEl.value : '';
  if (!uid) { dsSetStatus('Selecciona usuario en «Usuario (parcela)».', false); return; }
  dsSetStatus('Cargando snapshot…', undefined);
  try {
    const r = await fetch(DS_AI + '/api/dataset/snapshot?user_id=' + encodeURIComponent(uid));
    const data = await r.json();
    if (!r.ok) throw new Error((data.detail && (data.detail.msg || data.detail)) || JSON.stringify(data));
    document.getElementById('dsSnapshotJson').textContent = JSON.stringify(data, null, 2);
    const sel = document.getElementById('dsCropSelect');
    sel.innerHTML = (data.user_crops || []).map(c =>
      '<option value="' + c.id + '">' + (c.display_name || c.crop_name) + ' · ' + (c.crop_name||'') + ' (id ' + c.id + ')</option>'
    ).join('') || '<option value="">Sin cultivos</option>';
    const pcs = document.getElementById('dsProfileCrop');
    const catalog = data.crop_profiles_catalog || [];
    pcs.innerHTML = '<option value="">— elegir cultivo —</option>' + catalog.map(x =>
      '<option value="' + String(x.crop_name||'').replace(/"/g,'') + '">' + (x.crop_name||'') + '</option>'
    ).join('');
    dsClearUnifiedInputs();
    const pl = data.parcel_latest;
    const g = data.global_edaphology;
    if (g) {
      document.getElementById('dsLoc').value = g.location_name || '';
      dsFillField('dsSoilTemp', g.soil_temp);
      dsFillField('dsPh', g.ph);
      dsFillField('dsEc', g.conductivity);
      dsFillField('dsSm', g.soil_moisture);
      dsFillField('dsTa', g.air_temp);
      dsFillField('dsHa', g.air_humidity);
      dsFillField('dsPr', g.precipitation);
      dsFillField('dsWs', g.wind_speed);
      if (g.notes != null) document.getElementById('dsNotes').value = g.notes;
    }
    if (pl) {
      dsFillField('dsSm', pl.soil_moisture);
      dsFillField('dsTa', pl.air_temp);
      dsFillField('dsHa', pl.air_humidity);
      dsFillField('dsLi', pl.light);
      dsFillField('dsPr', pl.precipitation);
      dsFillField('dsWs', pl.wind_speed);
    }
    const meta = document.getElementById('dsStateMeta');
    if (meta) {
      const pAt = pl && pl.created_at ? pl.created_at : '—';
      const gLine = g ? ('Predio global id ' + g.id + ' · ' + (g.created_at || '')) : 'Sin registro en edaphology_global_readings';
      meta.textContent = 'Última parcela agregada: ' + pAt + ' · ' + gLine;
    }
    dsSetStatus('Vista actualizada.', true);
  } catch(e) {
    dsSetStatus('Error: ' + e.message, false);
  }
}

document.getElementById('dsBtnRefresh').addEventListener('click', dsRefreshSnapshot);

document.getElementById('dsBtnApply').addEventListener('click', async () => {
  const parcelOnly = document.getElementById('dsParcelOnly').checked;
  const uid = Number(document.getElementById('dsUserId').value);
  if (!uid) { dsSetStatus('Selecciona usuario en «Usuario (parcela)».', false); return; }
  const sm = dsNum('dsSm');
  const ta = dsNum('dsTa');
  const ha = dsNum('dsHa');
  const li = dsNum('dsLi');
  const pr = dsNum('dsPr');
  const ws = dsNum('dsWs');
  const needSensor = sm !== undefined || ta !== undefined || ha !== undefined || li !== undefined || pr !== undefined || ws !== undefined;
  const wantGlobal = !parcelOnly;
  if (parcelOnly && !needSensor) {
    dsSetStatus('Indica al menos un valor para la parcela o desmarca «solo escritura parcela» para actualizar predio.', false);
    return;
  }
  const parts = needSensor && wantGlobal
    ? ('INSERT en sensor_readings (parcela)\\nUPDATE edaphology_global_readings (predio)')
    : (needSensor ? 'INSERT en sensor_readings (parcela)' : 'UPDATE edaphology_global_readings (predio)');
  if (!dsConfirmRealWrite(parts)) return;
  const body = { user_id: uid };
  if (sm !== undefined) body.soil_moisture = sm;
  if (ta !== undefined) body.air_temp = ta;
  if (ha !== undefined) body.air_humidity = ha;
  if (li !== undefined) body.light = li;
  if (pr !== undefined) body.precipitation = pr;
  if (ws !== undefined) body.wind_speed = ws;
  if (document.getElementById('dsOneCrop').checked) {
    const cid = document.getElementById('dsCropSelect').value;
    if (!cid) { dsSetStatus('Elige un cultivo o desmarca «solo un cultivo».', false); return; }
    body.user_crop_id = Number(cid);
  }
  dsSetStatus('Aplicando…', undefined);
  try {
    let msg = '';
    if (needSensor) {
      const r1 = await fetch(DS_AI + '/api/dataset/apply-sensor-reading', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data1 = await r1.json();
      if (!r1.ok) throw new Error((data1.detail && (data1.detail.msg || data1.detail)) || JSON.stringify(data1));
      msg = 'Parcela: ' + data1.inserted_count + ' INSERT(s).';
    }
    if (wantGlobal) {
      const payload = {
        location_name: (document.getElementById('dsLoc').value || 'general').trim() || 'general',
        notes: (document.getElementById('dsNotes').value || '').trim(),
      };
      const st = dsNum('dsSoilTemp'); if (st !== undefined) payload.soil_temp = st;
      if (ta !== undefined) payload.air_temp = ta;
      if (ha !== undefined) payload.air_humidity = ha;
      if (sm !== undefined) payload.soil_moisture = sm;
      if (pr !== undefined) payload.precipitation = pr;
      if (ws !== undefined) payload.wind_speed = ws;
      const ph = dsNum('dsPh'); if (ph !== undefined) payload.ph = ph;
      const ec = dsNum('dsEc'); if (ec !== undefined) payload.conductivity = ec;
      const r2 = await fetch(DS_AI + '/api/edaphology/global/latest', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data2 = await r2.json();
      if (!r2.ok) throw new Error((data2.detail && (data2.detail.msg || data2.detail)) || JSON.stringify(data2));
      msg = (msg ? msg + ' ' : '') + 'Predio global: UPDATE id ' + data2.id + '.';
    }
    if (!msg) dsSetStatus('Sin operaciones.', false);
    else { dsSetStatus(msg, true); dsRefreshSnapshot(); }
  } catch(e) {
    dsSetStatus('Error: ' + e.message, false);
  }
});

document.getElementById('dsBtnLoadProfile').addEventListener('click', async () => {
  const cn = document.getElementById('dsProfileCrop').value;
  if (!cn) { dsSetStatus('Elige un cultivo en la lista.', false); return; }
  dsSetStatus('Cargando perfil…', undefined);
  try {
    const r = await fetch(DS_AI + '/api/edaphology/crop-profile/' + encodeURIComponent(cn));
    const p = await r.json();
    if (!r.ok || !p) throw new Error(p && p.detail ? p.detail : 'Sin perfil');
    document.getElementById('dsPfCd').value = p.cycle_days != null ? p.cycle_days : '';
    document.getElementById('dsPfVar').value = p.variety || '';
    document.getElementById('dsPfTmin').value = p.optimal_temp_min != null ? p.optimal_temp_min : '';
    document.getElementById('dsPfTmax').value = p.optimal_temp_max != null ? p.optimal_temp_max : '';
    document.getElementById('dsPfSmin').value = p.optimal_soil_moisture_min != null ? p.optimal_soil_moisture_min : '';
    document.getElementById('dsPfSmax').value = p.optimal_soil_moisture_max != null ? p.optimal_soil_moisture_max : '';
    document.getElementById('dsPfHmin').value = p.optimal_air_humidity_min != null ? p.optimal_air_humidity_min : '';
    document.getElementById('dsPfHmax').value = p.optimal_air_humidity_max != null ? p.optimal_air_humidity_max : '';
    document.getElementById('dsPfPhMin').value = p.optimal_ph_min != null ? p.optimal_ph_min : '';
    document.getElementById('dsPfPhMax').value = p.optimal_ph_max != null ? p.optimal_ph_max : '';
    document.getElementById('dsPfNotes').value = p.notes || '';
    dsSetStatus('Perfil cargado.', true);
  } catch(e) {
    dsSetStatus('Error: ' + e.message, false);
  }
});

document.getElementById('dsBtnSaveProfile').addEventListener('click', async () => {
  const cn = document.getElementById('dsProfileCrop').value;
  if (!cn) { dsSetStatus('Elige un cultivo.', false); return; }
  if (!dsConfirmRealWrite(
    'Se actualizará la fila del cultivo «' + cn + '» en crop_profiles (umbrales de todo el sistema para ese cultivo).'
  )) return;
  const patch = {};
  const cd = document.getElementById('dsPfCd').value.trim();
  if (cd !== '') patch.cycle_days = parseInt(cd, 10);
  const vv = document.getElementById('dsPfVar').value.trim(); if (vv !== '') patch.variety = vv;
  const tmin = dsNum('dsPfTmin'); if (tmin !== undefined) patch.optimal_temp_min = tmin;
  const tmax = dsNum('dsPfTmax'); if (tmax !== undefined) patch.optimal_temp_max = tmax;
  const smin = dsNum('dsPfSmin'); if (smin !== undefined) patch.optimal_soil_moisture_min = smin;
  const smax = dsNum('dsPfSmax'); if (smax !== undefined) patch.optimal_soil_moisture_max = smax;
  const hmin = dsNum('dsPfHmin'); if (hmin !== undefined) patch.optimal_air_humidity_min = hmin;
  const hmax = dsNum('dsPfHmax'); if (hmax !== undefined) patch.optimal_air_humidity_max = hmax;
  const phn = dsNum('dsPfPhMin'); if (phn !== undefined) patch.optimal_ph_min = phn;
  const phx = dsNum('dsPfPhMax'); if (phx !== undefined) patch.optimal_ph_max = phx;
  const nt = document.getElementById('dsPfNotes').value.trim(); if (nt !== '') patch.notes = nt;
  if (Object.keys(patch).length === 0) { dsSetStatus('No hay cambios que guardar.', false); return; }
  dsSetStatus('Guardando perfil…', undefined);
  try {
    const r = await fetch(DS_AI + '/api/edaphology/crop-profile/' + encodeURIComponent(cn), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    const data = await r.json();
    if (!r.ok) throw new Error((data.detail && (data.detail.msg || data.detail)) || JSON.stringify(data));
    dsSetStatus('Perfil actualizado.', true);
    dsRefreshSnapshot();
  } catch(e) {
    dsSetStatus('Error: ' + e.message, false);
  }
});

// ─── Init ─────────────────────────────────────────────────────────────────────
loadUsers();
<\/script>
</body>
</html>`;
    return rep.type('text/html').send(html);
});
// Arranque del servidor
app.listen({ port: config.PORT, host: "0.0.0.0" })
    .then(() => app.log.info(`Presenter listening on ${config.PORT}`))
    .catch((err) => {
    app.log.error(err);
    // Evitar dependencia de @types/node para 'process'. Lanzamos para terminar el proceso.
    throw err;
});
