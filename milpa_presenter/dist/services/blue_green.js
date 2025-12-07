// milpa_presenter/src/services/blue_green.ts
// Blue-Green deployment: router para dirigir tráfico entre UI v1 y v2
// SPRINT 20: Canary rollout con % configurable
let config = {
    v2Enabled: false,
    rolloutPercent: 0
};
/**
 * Actualiza configuración de blue-green desde backend AI.
 * El backend expone feature flags en /admin/feature-flags
 */
export async function updateBlueGreenConfig(iaUrl) {
    try {
        const response = await fetch(`${iaUrl}/admin/feature-flags/BLUE_GREEN_V2_ENABLED`);
        if (!response.ok) {
            console.warn('Could not fetch blue-green config from AI backend');
            return;
        }
        const data = await response.json();
        config.v2Enabled = data.enabled || false;
        config.rolloutPercent = data.config?.rollout_percent || 0;
        console.log(`Blue-Green config updated: v2=${config.v2Enabled}, rollout=${config.rolloutPercent}%`);
    }
    catch (err) {
        console.error('Error updating blue-green config:', err);
    }
}
/**
 * Decide si request debe ir a v2 basado en canary rollout.
 * Usa hash de sessionId para distribución estable (mismo usuario siempre v1 o v2).
 */
export function shouldRouteToV2(sessionId) {
    if (!config.v2Enabled) {
        return false;
    }
    if (config.rolloutPercent >= 100) {
        return true;
    }
    if (config.rolloutPercent <= 0) {
        return false;
    }
    // Hash simple de sessionId para distribución estable
    const hash = simpleHash(sessionId);
    const bucket = hash % 100;
    return bucket < config.rolloutPercent;
}
/**
 * Middleware de Fastify para routing blue-green automático.
 * Nota: Requiere @fastify/cookie instalado.
 */
export function blueGreenMiddleware(app) {
    app.addHook('onRequest', async (request, reply) => {
        // Solo aplicar a rutas /ui/*
        if (!request.url.startsWith('/ui/')) {
            return;
        }
        // Obtener sessionId de cookie o generar uno
        const sessionId = (request.cookies && request.cookies['session_id']) || generateSessionId();
        // Establecer cookie si no existe
        if (!request.cookies || !request.cookies['session_id']) {
            if (reply.setCookie) {
                reply.setCookie('session_id', sessionId, {
                    httpOnly: true,
                    maxAge: 86400 * 30 // 30 días
                });
            }
        }
        // Decidir routing
        const useV2 = shouldRouteToV2(sessionId);
        if (useV2 && !request.url.startsWith('/ui/v2/')) {
            // Redirigir a v2
            const v2Url = request.url.replace('/ui/', '/ui/v2/');
            if (reply.redirect) {
                reply.redirect(v2Url);
                return;
            }
        }
        // Continuar con v1 (comportamiento por defecto)
    });
}
/**
 * Hash simple para distribución de canary.
 */
function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    return Math.abs(hash);
}
/**
 * Genera sessionId único.
 */
function generateSessionId() {
    return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
}
/**
 * Obtiene configuración actual de blue-green (para debugging).
 */
export function getBlueGreenConfig() {
    return { ...config };
}
