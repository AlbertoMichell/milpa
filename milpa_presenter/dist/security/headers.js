// milpa_presenter/src/security/headers.ts
// Headers de endurecimiento: evita carga de recursos externos (CSP estricta)
// y deshabilita sniffing de MIME.
import fp from "fastify-plugin";
async function headersPlugin(app) {
    app.addHook("onSend", async (_req, reply, payload) => {
        reply.header("X-Content-Type-Options", "nosniff");
        reply.header("X-Frame-Options", "DENY");
        reply.header("Referrer-Policy", "no-referrer");
        // HSTS (solo tiene efecto sobre HTTPS; en HTTP es ignorado por navegadores)
        reply.header("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
        // CSP: bloquear cualquier contenido externo por defecto.
        reply.header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
        return payload;
    });
}
export const securityHeaders = fp(headersPlugin, {
    name: "security-headers"
});
