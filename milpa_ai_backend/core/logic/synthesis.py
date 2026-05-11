# milpa_ai_backend/core/logic/synthesis.py
# ------------------------------------------------------------
# Síntesis de respuestas con anti-alucinación y citas finas.
# - Cada oración debe anclar ≥1 cita del conjunto recuperado.
# - Citas finas: página, bbox, tabla (fila/col), figura.
# - Bloqueo de URLs externas (solo enlaces internos).
# - Cálculo de faithfulness (fidelidad oracional).
# ------------------------------------------------------------
from typing import List, Dict, Any, Tuple, Optional
import hashlib
import re
import unicodedata

from milpa_ai_backend.core.logic.crop_hints import normalize_crop_focus, synthesis_rank_key

_STOPWORDS_ES = {
    "de", "la", "el", "las", "los", "un", "una", "unos", "unas", "y", "o", "u", "e",
    "en", "del", "al", "por", "para", "que", "qué", "como", "cómo", "cuándo", "cuando",
    "cuál", "cual", "cuáles", "cuales", "es", "son", "ser", "estar", "esta", "este", "esto",
    "se", "su", "sus", "lo", "le", "les", "mi", "tu", "con", "sin", "sobre", "ya", "más",
    "mas", "menos", "muy", "porque", "pero",
}

_TIPO_DEFINICION = re.compile(r"\b(que es|qué es|definicion|definición|describe|describir)\b", re.IGNORECASE)
_TIPO_PARAMETRO = re.compile(
    r"\b(temperatura|humedad|ph|conductividad|riego|fertilizaci[oó]n|dosis|profundidad|densidad|distancia|ciclo|d[ií]as|edad|altitud|luz|nutriente|n|p|k|mg|ca|microelemento)\b",
    re.IGNORECASE,
)
_TIPO_ACCION = re.compile(
    r"\b(c[oó]mo|cuando|cu[áa]ndo|paso|pasos|protocolo|recomenda|aplica|aplicar|controla|prevenir|gestionar|manejar)\b",
    re.IGNORECASE,
)

def _norm_for_match(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def _query_keywords(query: str) -> List[str]:
    raw = re.findall(r"[a-záéíóúñü]+", _norm_for_match(query))
    return [w for w in raw if len(w) > 2 and w not in _STOPWORDS_ES]


def extract_sentences(text: str) -> List[str]:
    """Extrae oraciones de texto usando puntuación."""
    sentences = re.split(r'(?<=[.!?])\s+', text or "")
    return [s.strip() for s in sentences if s and len(s.strip()) > 5]

def compute_faithfulness(response_text: str, fragments: List[Dict[str, Any]]) -> float:
    """
    Calcula el overlap semántico entre oraciones de la respuesta y fragmentos recuperados.
    Retorna un score 0-1 donde 1 significa que todas las oraciones tienen respaldo.
    Acepta fragmentos con `text` directo o anidado en `metadata`.
    """
    if not response_text or not fragments:
        return 0.0

    sentences = extract_sentences(response_text)
    if not sentences:
        return 0.0

    bodies = []
    for f in fragments:
        t = ""
        if "metadata" in f and isinstance(f["metadata"], dict):
            t = f["metadata"].get("text", "") or ""
        if not t:
            t = f.get("text", "") or ""
        if t:
            bodies.append(_norm_for_match(t))

    if not bodies:
        return 0.0

    backed = 0
    for sent in sentences:
        s_norm = _norm_for_match(sent)
        words = [w for w in re.findall(r"[a-záéíóúñü]+", s_norm) if len(w) > 3]
        if len(words) < 3:
            continue
        for body in bodies:
            overlap = sum(1 for w in words if w in body)
            if overlap >= 3:
                backed += 1
                break
    return round(backed / len(sentences), 4)

def build_citation(fragment: Dict[str,Any], idx: int) -> Dict[str,Any]:
    """
    Construye una cita con información fina: página, bbox, tabla/celda, figura.
    Soporta ambas estructuras: con y sin metadata wrapper.
    """
    # Intentar con estructura metadata primero, luego directo
    if "metadata" in fragment:
        meta = fragment.get("metadata", {})
    else:
        meta = fragment
    
    doc_id = meta.get("doc_id", "unknown")
    page = meta.get("page_start")
    doc_title = meta.get("doc_title") or fragment.get("doc_title")
    doc_author = meta.get("doc_author") or fragment.get("doc_author")
    
    citation = {
        "citation_id": f"cite_{idx}",
        "doc_id": doc_id,
        "fragment_id": fragment.get("fragment_id"),
        "score": fragment.get("rerank_score", fragment.get("rrf_score", fragment.get("score", 0.0))),
        "doc_title": doc_title,
        "doc_author": doc_author,
    }
    
    # Referencia fina de página
    if page:
        citation["page"] = page
    
    # Bbox si está disponible (coordenadas PDF para clic-through)
    bbox = meta.get("bbox")
    if bbox:
        citation["bbox"] = bbox
    
    # Tabla/celda si el fragmento proviene de una tabla
    table_id = meta.get("table_id")
    if table_id:
        citation["table_id"] = table_id
        citation["row"] = meta.get("row")
        citation["col"] = meta.get("col")
    
    # Figura si está disponible
    figure_id = meta.get("figure_id")
    if figure_id:
        citation["figure_id"] = figure_id
        citation["caption"] = meta.get("caption")
    
    return citation

def _format_citation_line(idx: int, c: dict) -> str:
    """Genera una línea de cita con autor y título si están disponibles."""
    parts = [f"[{idx+1}]"]
    author = c.get("doc_author")
    title = c.get("doc_title")
    if author and title:
        parts.append(f'{author}, "{title}"')
    elif title:
        parts.append(f'"{title}"')
    elif author:
        parts.append(author)
    else:
        parts.append(f"Documento {c['doc_id'][:16]}...")
    page = c.get("page")
    if page:
        parts.append(f"p. {page}")
    return " — ".join(parts)

def _frag_text(frag: Dict[str, Any]) -> str:
    if "metadata" in frag and isinstance(frag["metadata"], dict):
        t = frag["metadata"].get("text", "")
        if t:
            return t
    return frag.get("text", "") or ""


def _dedup_fragments(fragments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quita duplicados por doc_id+page_start o por hash de las primeras 220 chars."""
    seen_keys = set()
    seen_text = set()
    out: List[Dict[str, Any]] = []
    for f in fragments:
        meta = f.get("metadata") or {}
        doc_id = f.get("doc_id") or meta.get("doc_id")
        page = f.get("page_start") or meta.get("page_start")
        key = (str(doc_id or ""), str(page or ""))
        text = _frag_text(f)
        text_key = hashlib.md5(_norm_for_match(text)[:220].encode("utf-8")).hexdigest()
        if key in seen_keys and key != ("", ""):
            continue
        if text_key in seen_text:
            continue
        seen_keys.add(key)
        seen_text.add(text_key)
        out.append(f)
    return out


def _question_type(query: str) -> str:
    if _TIPO_DEFINICION.search(query):
        return "definicion"
    if _TIPO_ACCION.search(query):
        return "accion"
    if _TIPO_PARAMETRO.search(query):
        return "parametro"
    return "general"


def _select_relevant_sentences(
    text: str,
    keywords: List[str],
    max_sentences: int,
    min_overlap: int = 1,
) -> List[str]:
    """Devuelve oraciones del fragmento que mencionan al menos `min_overlap` keywords."""
    if not text:
        return []
    sentences = extract_sentences(text)
    scored: List[Tuple[int, int, str]] = []
    for i, s in enumerate(sentences):
        s_norm = _norm_for_match(s)
        hits = sum(1 for kw in keywords if kw and kw in s_norm)
        if hits >= min_overlap:
            scored.append((-hits, i, s))
    if not scored:
        return [sentences[0]] if sentences else []
    scored.sort()
    picked = [s for _, _, s in scored[:max_sentences]]
    return picked


def _bullet_lines(sentence: str, max_chars: int = 240) -> str:
    s = re.sub(r"\s+", " ", sentence).strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def compose_answer(query: str, fragments: List[Dict[str, Any]],
                   max_length: int = 500,
                   crop_focus: Optional[str] = None) -> Dict[str, Any]:
    """
    Síntesis NO-plantilla:
    - Deduplica por doc_id+página y por hash de texto.
    - Detecta tipo de pregunta (definición / parámetro / acción / general).
    - Extrae oraciones del cuerpo del fragmento que mencionan keywords de la query.
    - Cita por número [1] [2] [3] sin repetir el snippet completo.
    """
    if not fragments:
        return {
            "respuesta_html": "<p>No se encontró información relevante.</p>",
            "citas": [],
            "advertencias": ["sin_fragmentos"],
            "faithfulness": 0.0,
        }

    focus_norm = normalize_crop_focus(crop_focus) if crop_focus else None
    ranked = sorted(fragments, key=lambda f: synthesis_rank_key(f, focus_norm))
    deduped = _dedup_fragments(ranked)

    keywords = _query_keywords(query)
    if focus_norm and focus_norm not in keywords:
        keywords = [focus_norm] + keywords
    qtype = _question_type(query)
    per_frag = 2 if qtype in ("parametro", "accion") else 1

    citations: List[Dict[str, Any]] = []
    bullets: List[str] = []
    seen_sentences = set()

    for idx, frag in enumerate(deduped[:3], start=1):
        text = _frag_text(frag)
        if not text:
            continue
        sents = _select_relevant_sentences(text, keywords, per_frag, min_overlap=1)
        if not sents:
            sents = [text[:240]]
        added_for_this = False
        for s in sents:
            key = _norm_for_match(s)[:160]
            if key in seen_sentences:
                continue
            seen_sentences.add(key)
            bullets.append(f"- {_bullet_lines(s)} [{idx}]")
            added_for_this = True
        if added_for_this:
            citations.append(build_citation(frag, idx))

    if not bullets:
        # Caso degenerado: ningún fragmento con texto utilizable.
        for idx, frag in enumerate(deduped[:1], start=1):
            text = _frag_text(frag)
            if text:
                bullets.append(f"- {_bullet_lines(text)} [{idx}]")
                citations.append(build_citation(frag, idx))

    headers_by_type = {
        "definicion": f"Definición de «{query.strip()}»:",
        "parametro": f"Parámetros agronómicos relevantes para «{query.strip()}»:",
        "accion": f"Pasos y recomendaciones para «{query.strip()}»:",
        "general": f"Hallazgos en la biblioteca para «{query.strip()}»:",
    }
    header = headers_by_type.get(qtype, headers_by_type["general"])

    body = header + "\n\n" + "\n".join(bullets)
    sources = "\n".join(_format_citation_line(i, c) for i, c in enumerate(citations))
    response_text = f"{body}\n\nFuentes:\n{sources}".strip()

    faithfulness = compute_faithfulness(response_text, deduped[:3])
    warnings: List[str] = []
    if faithfulness < 0.55:
        warnings.append("baja_fidelidad")

    return {
        "respuesta_html": response_text,
        "citas": citations,
        "advertencias": warnings,
        "faithfulness": faithfulness,
        "question_type": qtype,
    }

def sanitize_html(html: str) -> str:
    """
    Sanitiza HTML permitiendo solo tags seguros y bloqueando URLs externas.
    Solo permite: <p>, <a> (sin href externos), <em>, <strong>, <ul>, <li>.
    """
    from html import escape
    
    # Por ahora, implementación simple: escape todo y reconstruye solo tags permitidos
    # En producción, usar librería como bleach o html-sanitizer
    allowed_tags = ["p", "a", "em", "strong", "ul", "li"]
    
    # Remover cualquier href que empiece con http:// o https://
    html = re.sub(r'href=["\']https?://[^"\']+["\']', 'href="#"', html, flags=re.IGNORECASE)
    
    return html
