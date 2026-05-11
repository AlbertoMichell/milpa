# milpa_ai_backend/core/logic/extract_layout.py
# Heurísticas alineadas con pipelines tipo Document AI / layout-aware RAG (sin modelos
# en la nube): orden de lectura por bloques (bbox y,x), columnas, limpieza,
# cabeceras/piés repetidos, solapamiento de chunks. Inspirado en: orden de bloques
# con coordenadas (Document AI, ÉCLAIR), chunking con contexto (Gemini layout parser).

from __future__ import annotations

import re
import statistics
import unicodedata
from typing import List, Tuple

import fitz  # PyMuPDF

_RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Caracteres invisibles habituales en PDFs (espacios estrechos, BOM, soft hyphen)
_RE_INVISIBLES = re.compile(r"[\u00ad\u200b-\u200d\ufeff]")
# Línea corta candidata a pie/número (no borrar líneas largas aunque repitan)
_RE_PAGE_FTR = re.compile(
    r"^(?:page|pag|p[áa]g\.?|p\.?)\s*\d+\s*(?:/|\s*de\s*|\s*of\s*)?\s*\d*\s*$",
    re.IGNORECASE,
)
_RE_LONE_NUM = re.compile(r"^\d{1,4}$")


def normalize_extracted_text(text: str) -> str:
    """Hifenación EOL, controles, espacios. Mejora fidelidad para RAG.

    Cubre tres patrones de partido al final de línea:
      1. Hifenación clásica: ``palab-\\nra`` → ``palabra``.
      2. Hifenación con espacios: ``palab- \\n ra``.
      3. Tokens largos partidos SIN guion: ``ABC_DEF\\nGHI_JKL`` cuando ambos
         lados son secuencias de ``[A-Z0-9_]`` de longitud ≥3 (típico de IDs,
         URLs y palabras compuestas en columnas estrechas). Conservador: se
         exige que las dos líneas estén pegadas (sin línea en blanco) y que el
         total quede sin espacios internos.
    """
    if not text:
        return ""
    # NFC asegura que vocales acentuadas vengan como un único code point (evita
    # divergencias entre OCR/PyMuPDF que a veces emiten formas decompuestas).
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _RE_CONTROL.sub("", t)
    t = _RE_INVISIBLES.sub("", t)
    t = re.sub(r"([a-záéíóúñ])-(\n)([a-záéíóúñ])", r"\1\3", t, flags=re.IGNORECASE)
    t = re.sub(r"([a-z])-\s*\n\s*([a-z])", r"\1\2", t, flags=re.IGNORECASE)
    # Tokens compuestos partidos sin guion (case típico: identificadores en columnas estrechas).
    t = re.sub(r"([A-Z0-9_]{3,})\n([A-Z0-9_]{3,})", r"\1\2", t)
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# Tupla de línea: (y0, x0, x1, texto)
def _line_boxes_from_dict(page: fitz.Page) -> List[Tuple[float, float, float, str]]:
    d = page.get_text("dict") or {}
    out: List[Tuple[float, float, float, str]] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            sp = line.get("spans", [])
            if not sp:
                continue
            parts = [s.get("text", "") for s in sp if s.get("text")]
            raw = "".join(parts)
            if not raw.strip():
                continue
            line_text = normalize_extracted_text(raw)
            if not line_text:
                continue
            bb = line.get("bbox", None)
            if not bb or len(bb) < 4:
                x0, y0, x1, y1 = 0.0, 0.0, 0.0, 0.0
            else:
                x0, y0, x1, y1 = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
            out.append((y0, x0, x1, line_text))
    return out


def _x_center(t: Tuple[float, float, float, str]) -> float:
    return (t[1] + t[2]) / 2.0


def _read_two_columns(lines: List[Tuple[float, float, float, str]], page: fitz.Page) -> str:
    if len(lines) < 6:
        return ""
    centers = [_x_center(a) for a in lines]
    try:
        w = float(page.rect.width)
    except Exception:
        w = max((a[2] for a in lines), default=1.0) or 1.0
    if w < 1:
        w = 1.0
    if len(centers) < 2 or statistics.stdev(centers) < w * 0.12:
        return ""
    med = statistics.median(centers)
    left = [ln for ln in lines if _x_center(ln) < med]
    right = [ln for ln in lines if _x_center(ln) >= med]
    if not left or not right:
        return ""
    left.sort(key=lambda t: (t[0], t[1]))
    right.sort(key=lambda t: (t[0], t[1]))
    parts: List[str] = []
    parts.append("\n".join(a[3] for a in left))
    parts.append("\n".join(a[3] for a in right))
    return "\n\n".join(parts)


def _detect_column_breaks(
    centers: List[float],
    page_w: float,
    n: int,
) -> List[float] | None:
    """Encuentra ``n-1`` cortes verticales que separan ``n`` columnas reales.

    Estrategia: ordenamos los centros, calculamos los huecos consecutivos y
    seleccionamos los ``n-1`` mayores como límites. Validamos que cada hueco
    tenga al menos un porcentaje mínimo del ancho de la página, lo que evita
    declarar columnas espurias en flujos de texto continuos.
    """
    if n < 2 or len(centers) < n * 2:
        return None
    sorted_c = sorted(centers)
    gaps = [
        (sorted_c[i + 1] - sorted_c[i], (sorted_c[i + 1] + sorted_c[i]) / 2.0)
        for i in range(len(sorted_c) - 1)
    ]
    if not gaps:
        return None
    gaps.sort(key=lambda g: g[0], reverse=True)
    top = gaps[: n - 1]
    # Filtrar huecos demasiado pequeños (< 8% del ancho de la página).
    threshold = max(page_w * 0.08, 30.0)
    if any(g[0] < threshold for g in top):
        return None
    cuts = sorted(g[1] for g in top)
    return cuts


def _read_n_columns(
    lines: List[Tuple[float, float, float, str]],
    page: fitz.Page,
    n: int,
) -> str:
    """Orden de lectura para n columnas (n>=2).

    Estrategia híbrida:
      1. Detección de gaps reales en el eje X (clusterización por huecos).
         Más robusta que dividir el ancho en bandas iguales cuando las
         columnas no son equiespaciadas o tienen título de ancho completo.
      2. Si no se detectan ``n-1`` huecos suficientemente anchos, se cae a
         bandas equiespaciadas como heurística secundaria.
    """
    if n < 2 or len(lines) < n * 3:
        return ""
    try:
        page_w = float(page.rect.width)
    except Exception:
        page_w = max((a[2] for a in lines), default=1.0) or 1.0
    if page_w < 1:
        page_w = 1.0

    centers = [_x_center(a) for a in lines]
    if len(centers) < n or statistics.stdev(centers) < page_w * 0.14:
        return ""

    columns: List[List[Tuple[float, float, float, str]]] = [[] for _ in range(n)]

    cuts = _detect_column_breaks(centers, page_w, n)
    if cuts is not None:
        for ln in lines:
            cx = _x_center(ln)
            idx = 0
            while idx < n - 1 and cx >= cuts[idx]:
                idx += 1
            columns[idx].append(ln)
    else:
        x_min = min(a[1] for a in lines)
        x_max = max(a[2] for a in lines)
        span = max(x_max - x_min, 1.0)
        band = span / n
        for ln in lines:
            cx = _x_center(ln)
            idx = int((cx - x_min) / band)
            if idx < 0:
                idx = 0
            elif idx >= n:
                idx = n - 1
            columns[idx].append(ln)

    if any(len(c) < 2 for c in columns):
        return ""

    parts: List[str] = []
    for col in columns:
        col.sort(key=lambda t: (t[0], t[1]))
        parts.append("\n".join(a[3] for a in col))
    return "\n\n".join(p for p in parts if p)


def read_page_text_layout_aware(page: fitz.Page) -> str:
    """Orden de lectura por cajas.

    Intenta layouts multicolumna en orden 3 → 2 → flujo único. La detección de
    3 columnas se aplica solo cuando los centros muestran tres modas razonables;
    si la heurística falla, cae a 2 columnas y luego a orden simple por (y, x).
    """
    lines = _line_boxes_from_dict(page)
    if not lines:
        return ""
    three = _read_n_columns(lines, page, 3)
    if three and len(three.strip()) > 120:
        return normalize_extracted_text(three)
    two = _read_two_columns(lines, page)
    if two and len(two.strip()) > 80:
        return normalize_extracted_text(two)
    lines.sort(key=lambda t: (t[0] + 0.001, t[1]))
    return normalize_extracted_text("\n".join(t[3] for t in lines if t[3]))


def pick_best_native_text(_page: fitz.Page, text_sort: str, text_layout: str) -> str:
    """Elige el texto con más contenido útil (evita layout vacío en PDFs raros)."""
    a = (text_layout or "").strip()
    b = (text_sort or "").strip()
    if not a and not b:
        return ""
    if not a:
        return b
    if not b:
        return a
    if len(a) < len(b) * 0.55 and len(b) > 200:
        return b
    if len(b) < len(a) * 0.55 and len(a) > 200:
        return a
    return a


def strip_repeating_page_lines(
    page_texts: List[str],
    min_ratio: float = 0.86,
    max_line_len: int = 120,
) -> List[str]:
    """
    Líneas cortas presentes en casi todas las páginas: cabeceras/piés (patrón ÉCLAIR:
    separar texto flotante repetido). Evita borrar líneas largas (cuerpo).
    """
    if not page_texts or len(page_texts) < 2:
        return page_texts
    n = len(page_texts)
    counts: dict[str, int] = {}
    for p in page_texts:
        seen: set[str] = set()
        for ln in p.split("\n"):
            s = ln.strip()
            if not s or len(s) > max_line_len:
                continue
            if s in seen:
                continue
            seen.add(s)
            counts[s] = counts.get(s, 0) + 1

    bad: set[str] = set()
    for line, c in counts.items():
        r = c / n
        if r < min_ratio:
            continue
        if _RE_LONE_NUM.match(line) or _RE_PAGE_FTR.match(line) or len(line) <= 3:
            bad.add(line)
            continue
        if r >= 0.95 and len(line) < 80:
            bad.add(line)

    out: List[str] = []
    for p in page_texts:
        lines = [ln for ln in p.split("\n") if ln.strip() and ln.strip() not in bad]
        out.append("\n".join(lines))
    return out


def apply_chunk_overlap(chunks: List[str], overlap: int) -> List[str]:
    """
    Solapamiento al estilo RAG/IA: el inicio de cada trozo re-incluye el final del
    anterior (contexto en recuperación; Document AI: chunks con ancestros).
    """
    if overlap <= 0 or len(chunks) < 2:
        return list(chunks)
    out: List[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        cur = chunks[i]
        tail = prev[-overlap:].strip() if len(prev) > overlap else prev.strip()
        if tail and tail not in (cur[: min(len(tail) + 12, len(cur))] if cur else ""):
            out.append(f"{tail}\n{cur}" if cur else cur)
        else:
            out.append(cur)
    return out


def prefer_split_at_sentence(chunk: str, max_len: int) -> str:
    """
    Si se corta un bloque largo, intenta acotar al último '. ' o '? ' o '! ' cerca
    del límite (mejor que cortar a mitad de frase).
    """
    if len(chunk) <= max_len or max_len < 50:
        return chunk
    window = chunk[:max_len]
    for sep in (". ", "? ", "! ", ".\n", ".\t"):
        pos = window.rfind(sep, max(0, max_len - 220))
        if pos > max_len // 2:
            return chunk[: pos + len(sep)].strip()
    return window.strip()
