// milpa_presenter/src/telemetry/metrics.ts
// Exposición básica de métricas Prometheus desde Presenter.
import client from "prom-client";
export const register = new client.Registry();
// Recolecta métricas por defecto: uso de CPU, memoria, etc.
client.collectDefaultMetrics({ register });
export const metricsPlugin = async (app) => {
    app.get("/metrics", async (_req, reply) => {
        reply.header("Content-Type", register.contentType);
        return register.metrics();
    });
};
// Métricas específicas de proxy/cola
export const queueInFlight = new client.Gauge({ name: 'milpa_queue_in_flight', help: 'Tareas en vuelo' });
export const queueDepth = new client.Gauge({ name: 'milpa_queue_depth', help: 'Tareas en cola' });
export const proxyTotal = new client.Counter({ name: 'milpa_proxy_total', help: 'Total de peticiones proxy a IA' });
export const proxy429 = new client.Counter({ name: 'milpa_proxy_429_total', help: 'Rechazos por cola llena' });
export const proxyTimeout = new client.Counter({ name: 'milpa_proxy_timeout_total', help: 'Timeouts hacia IA' });
export const circuitOpenTotal = new client.Counter({ name: 'milpa_circuit_open_total', help: 'Veces que el circuito abrió' });
export const proxyLatency = new client.Histogram({ name: 'milpa_proxy_latency_ms', help: 'Latencia proxy→IA', buckets: [50, 100, 200, 400, 800, 1500, 3000, 6000, 12000] });
register.registerMetric(queueInFlight);
register.registerMetric(queueDepth);
register.registerMetric(proxyTotal);
register.registerMetric(proxy429);
register.registerMetric(proxyTimeout);
register.registerMetric(circuitOpenTotal);
register.registerMetric(proxyLatency);
// ────────────────────────────────────────────────────────────────
// SPRINT 19: Métricas de negocio ampliadas
// ────────────────────────────────────────────────────────────────
// Calidad RAG: % de consultas con evidencia insuficiente
export const ragInsufficientEvidenceRate = new client.Gauge({
    name: 'milpa_rag_insufficient_evidence_rate',
    help: 'Porcentaje de consultas RAG con evidencia insuficiente (0-1)',
    labelNames: ['time_window'] // ej: '1h', '24h'
});
// Recall drop: degradación de recall en retrieval
export const retrievalRecallDrop = new client.Gauge({
    name: 'milpa_retrieval_recall_drop',
    help: 'Drop en recall de retrieval comparado con baseline (0-1)',
    labelNames: ['metric_type'] // ej: 'top5', 'top10'
});
// Métricas de negocio: recomendaciones aplicadas
export const recommendationsAppliedRate = new client.Gauge({
    name: 'milpa_recommendations_applied_rate',
    help: 'Porcentaje de recomendaciones técnicas marcadas como aplicadas (0-1)',
    labelNames: ['category'] // ej: 'nutrientes', 'plagas', 'riego'
});
// Top cultivos consultados
export const topCropsConsulted = new client.Counter({
    name: 'milpa_top_crops_consulted',
    help: 'Conteo de consultas por cultivo',
    labelNames: ['crop_name', 'region']
});
// Top plagas/enfermedades consultadas
export const topPestsConsulted = new client.Counter({
    name: 'milpa_top_pests_consulted',
    help: 'Conteo de consultas sobre plagas y enfermedades',
    labelNames: ['pest_name', 'crop']
});
// Versión de taxonomía en uso
export const taxonomyVersionGauge = new client.Gauge({
    name: 'milpa_taxonomy_version',
    help: 'Versión de taxonomía activa (timestamp como float)',
    labelNames: ['taxonomy_type'] // ej: 'crops', 'pests', 'nutrients'
});
register.registerMetric(ragInsufficientEvidenceRate);
register.registerMetric(retrievalRecallDrop);
register.registerMetric(recommendationsAppliedRate);
register.registerMetric(topCropsConsulted);
register.registerMetric(topPestsConsulted);
register.registerMetric(taxonomyVersionGauge);
