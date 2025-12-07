// milpa_presenter/src/security/sanitize.ts
// Sanitización HTML con allowlist y bloqueo de enlaces externos.
import sanitizeHtmlLib from "sanitize-html";

// Rutas internas permitidas (prefijos)
const INTERNAL_PREFIXES = ["/", "#", "?", "./", "../"];

export function sanitizeHtmlSafe(input: string): string {
  const out = sanitizeHtmlLib(input, {
    // Solo permitir un subconjunto pequeño y controlado
    allowedTags: ["a", "em", "strong", "ul", "ol", "li", "p", "br", "code", "pre"],
    allowedAttributes: {
      a: [
        "href",
        // Metadatos para clic-through interno
        "data-cite",
        "data-page",
        "data-bbox",
        "data-table",
        "data-row",
        "data-col",
      ],
    },
    // Bloquear cualquier esquema (http, https, mailto, etc.)
    allowedSchemes: [],
    allowedSchemesByTag: { a: [] },
    allowProtocolRelative: false,
    // Transformar enlaces externos en '#'
    transformTags: {
      a: (_tagName: any, attribs: any) => {
        const href = (attribs?.href as string) ?? "";
        const isInternal = INTERNAL_PREFIXES.some((p) => href.startsWith(p));
        return {
          tagName: "a",
          attribs: {
            ...attribs,
            href: isInternal ? href : "#",
          },
        } as any;
      },
    },
    // Eliminar cualquier tag/attr no listado
    disallowedTagsMode: "discard",
    // Estrictamente sin estilos/eventos
    allowedStyles: {},
    allowIframeRelativeUrls: false,
  });
  return out;
}

export const sanitizePlugin = async (app: any) => {
  app.addHook("onSend", async (_req: any, rep: any, payload: any) => {
    try {
      // Sanitizar si parece HTML (string con tags)
      if (typeof payload === "string" && payload.includes("<")) {
        const clean = sanitizeHtmlSafe(payload);
        // Si no estaba seteado, forzar content-type a text/html
        const ctype = String(rep.getHeader("content-type") || "").toLowerCase();
        if (!ctype) rep.header("Content-Type", "text/html; charset=utf-8");
        return clean;
      }
    } catch (e) {
      // En caso de error, devolver payload original
      return payload;
    }
    return payload;
  });
};
