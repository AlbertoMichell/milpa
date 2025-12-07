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
const circuit = new CircuitBreaker(config.CIRCUIT_OPEN_SECS);
await app.register(sanitizePlugin);
// Log de diagnóstico: a qué IA_URL estamos apuntando
app.log.info({ IA_URL: config.IA_URL }, 'Configuración de IA_URL');
// Healthcheck básico
app.get("/health", async () => ({ ok: true }));
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
        const suffix = req.url.replace(/^\/ai\//, '');
        const target = new URL(suffix, config.IA_URL).toString();
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
        // Encolar ejecución con control de concurrencia, deadline y métrica de latencia
        const start = Date.now();
        queueInFlight.set(scheduler.stats.inFlight);
        queueDepth.set(scheduler.stats.queued);
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(new Error('upstream_timeout')), config.UPSTREAM_TIMEOUT_MS);
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
    </style>
  </head>
  <body>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
      <div>
        <h1 style="margin-bottom:4px">Biblioteca</h1>
        <div class="muted">Explora y filtra los documentos disponibles. Usa los filtros avanzados para encontrar exactamente lo que necesitas.</div>
      </div>
      <div style="display:flex; gap:8px">
        <a href="/ui/query" class="btn btn-primary">Consultas RAG</a>
        <a href="/ui/checks" class="btn">← Verificaciones</a>
      </div>
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
        </div>
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
          const mode = document.getElementById('modeSelect').value;
          const k = parseInt(document.getElementById('kInput').value) || 5;

          const response = await fetch('/ai/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, k, mode })
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
// Arranque del servidor
app.listen({ port: config.PORT, host: "0.0.0.0" })
    .then(() => app.log.info(`Presenter listening on ${config.PORT}`))
    .catch((err) => {
    app.log.error(err);
    // Evitar dependencia de @types/node para 'process'. Lanzamos para terminar el proceso.
    throw err;
});
