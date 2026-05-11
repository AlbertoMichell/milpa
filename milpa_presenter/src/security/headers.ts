// milpa_presenter/src/security/headers.ts
// Headers de endurecimiento: evita carga de recursos externos (CSP estricta)
// y deshabilita sniffing de MIME.
//
// connect-src debe permitir el origen de IA_URL: la UI a veces llama a la API en
// :8000 (mismo host que el presenter, otro origen) o, preferible, /ai/* (proxy
// same-origin), pero enlaces/healths directos a :8000 siguen necesitando CSP.

import fp from "fastify-plugin";
import { config } from "../config.js";

/** Orígenes permitidos para fetch/XHR: 'self' (:8080) + backend IA (p. ej. :8000), con par localhost↔127.0.0.1 en dev. */
function buildConnectSrc(): string {
  const o = new Set<string>(["'self'"]);
  try {
    const u = new URL(config.IA_URL);
    o.add(u.origin);
    const port = u.port || (u.protocol === "https:" ? "443" : u.protocol === "http:" ? "80" : "");
    if (port) {
      if (u.hostname === "127.0.0.1") {
        o.add(`http://localhost:${port}`);
      } else if (u.hostname === "localhost") {
        o.add(`http://127.0.0.1:${port}`);
      }
    }
  } catch {
    /* no romper el arranque si IA_URL no es URL válida */
  }
  return Array.from(o).join(" ");
}

async function headersPlugin(app: any) {
  const connectSrc = buildConnectSrc();
  app.addHook("onSend", async (_req: any, reply: any, payload: any) => {
    reply.header("X-Content-Type-Options", "nosniff");
    reply.header("X-Frame-Options", "DENY");
    reply.header("Referrer-Policy", "no-referrer");
    // HSTS (solo tiene efecto sobre HTTPS; en HTTP es ignorado por navegadores)
    reply.header("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
    // CSP: el backend IA es otro origen (mismo host, distinto puerto) → listado en connect-src.
    reply.header(
      "Content-Security-Policy",
      `default-src 'none'; script-src 'unsafe-inline'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src ${connectSrc}; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
    );
    return payload;
  });
}

export const securityHeaders = fp(headersPlugin, {
  name: "security-headers"
});
