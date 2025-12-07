# milpa_ai_backend/core/logic/chunking.py
# ------------------------------------------------------------
# Chunking basado en tokens del tokenizer del modelo de embeddings (HF).
#   - Ventanas objetivo: 800–1200 tokens (configurable).
#   - Solapamiento: 15–20% (configurable).
#   - Protección de ecuaciones (LaTeX/Unicode math) con sentinelas.
#   - Normalización ligera de unidades (regex + map canónico).
#   - fragment_uid determinista por (doc_id, section_id, page_start, hash(text[:N])).
# Entradas típicas:
#   pages: [{"page":int, "text":str, "spans":[...]}]  (de extraction.py)
# Salida: lista de fragments listos para persistir en SQLite (tabla fragments)
#         + opcional fine_ref por fragment (bbox intermedio si existe).
# ------------------------------------------------------------
from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import hashlib
import re

# Tokenizer (opcional)
try:
    from transformers import AutoTokenizer
except Exception:
    AutoTokenizer = None


# -------- Unidades: normalización básica --------
_UNIT_CANON = {
    r"\bkg\s*/\s*ha\b": "kg/ha",
    r"\bl\s*/\s*ha\b": "L/ha",
    r"\bg\s*/\s*l\b": "g/L",
    r"\b°\s*C\b": "°C",
    r"\bppm\b": "ppm",
}

def normalize_units(text: str) -> str:
    out = text
    for pattern, repl in _UNIT_CANON.items():
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    # normaliza espacios y separadores decimales comunes (simple)
    out = re.sub(r"\s+", " ", out).strip()
    return out


# -------- Ecuaciones: protección --------
EQN = re.compile(
    r"(\$[^$]+\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|"  # LaTeX $...$, \[...\], \(...\)
    r"[∑∏√≈≃≤≥±×÷]|"                                  # Símbolos matemáticos comunes
    r"[A-Za-z]\s*=\s*[^;\n]+)"                        # Asignaciones simples A = ...
)

def _protect_equations(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Reemplaza ecuaciones por sentinelas y devuelve mapping para restaurar.
    """
    mapping: Dict[str, str] = {}
    def _sub(m):
        h = hashlib.sha1(m.group(0).encode()).hexdigest()[:10]
        key = f"⟦EQN_{h}⟧"
        mapping[key] = m.group(0)
        return key
    return EQN.sub(_sub, text), mapping

def _restore_equations(text: str, mapping: Dict[str, str]) -> str:
    out = text
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


# -------- Tokenizador y ventanas --------
def _get_tokenizer(model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    """
    Carga tokenizer HF. Si no está disponible, lanza error comprensible.
    """
    if AutoTokenizer is None:
        raise RuntimeError("transformers no está instalado. Instálalo para usar chunking por tokens.")
    try:
        tok = AutoTokenizer.from_pretrained(model_name)
        return tok
    except Exception as e:
        # Fallback: intenta sin el prefijo sentence-transformers
        try:
            alt = model_name.replace("sentence-transformers/", "")
            return AutoTokenizer.from_pretrained(alt)
        except Exception:
            raise RuntimeError(f"No se pudo cargar tokenizer para '{model_name}': {e}")


def _split_by_tokens(text: str, target: int = 1000, overlap: float = 0.2, tokenizer=None) -> List[str]:
    """
    Divide el texto por tokens del tokenizer:
      - ventanas de tamaño 'target' con paso 'target*(1-overlap)'.
    """
    if tokenizer is None:
        tokenizer = _get_tokenizer()

    ids = tokenizer.encode(text, add_special_tokens=False)
    step = max(int(target * (1 - overlap)), 1)
    chunks: List[str] = []
    for s in range(0, len(ids), step):
        win = ids[s : s + target]
        if not win:
            break
        chunks.append(tokenizer.decode(win))
    return chunks


def _fragment_uid(doc_id: str, section_id: str, page_start: int, text: str, prefix_len: int = 64) -> str:
    """
    ID determinista por doc, sección y hash de prefijo de texto normalizado.
    """
    h = hashlib.sha1(text[:prefix_len].encode()).hexdigest()
    base = f"{doc_id}|{section_id}|{page_start}|{h}"
    return hashlib.sha1(base.encode()).hexdigest()


def chunk_pages(
    doc_id: str,
    pages: List[Dict[str, Any]],
    section_id: str = "body",
    target_tokens: int = 1000,
    overlap: float = 0.2,
    tokenizer_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
) -> List[Dict[str, Any]]:
    """
    Crea fragmentos a partir de páginas: protege ecuaciones, normaliza unidades,
    y corta por tokens del modelo de embeddings.
    Retorna estructura lista para persistir en 'fragments' y 'fine_refs'.
    """
    tokenizer = _get_tokenizer(tokenizer_name)
    fragments: List[Dict[str, Any]] = []

    for p in pages:
        page_no = int(p["page"])
        raw_text = p.get("text") or ""
        # Normaliza unidades y protege ecuaciones
        norm = normalize_units(raw_text)
        protected, eq_map = _protect_equations(norm)

        # Ventanas por tokens
        windows = _split_by_tokens(protected, target=target_tokens, overlap=overlap, tokenizer=tokenizer)

        # Fine-ref heuristic: usa bbox del span medio de la página si existe
        fine_ref = None
        spans = p.get("spans") or []
        if isinstance(spans, list) and spans:
            mid = spans[len(spans) // 2]
            bbox = mid.get("bbox") if isinstance(mid, dict) else getattr(mid, "bbox", None)
            if bbox:
                fine_ref = {"page": page_no, "bbox": bbox}

        for w in windows:
            # Restaurar ecuaciones
            restored = _restore_equations(w, eq_map)
            frag = {
                "fragment_id": None,   # lo puedes asignar en la persistencia
                "doc_id": doc_id,
                "fragment_uid": _fragment_uid(doc_id, section_id, page_no, restored),
                "section_id": section_id,
                "page_start": page_no,
                "page_end": page_no,
                "text": raw_text,      # texto original por página (opcional)
                "text_es": restored,   # texto normalizado listo (si ya está en ES o pasará por traducción)
                "source": "native",    # o "ocr" si aplicó OCR antes de chunkear
                "tokenizer_name": tokenizer_name,
                "fine_ref": fine_ref,  # para tabla 'fine_refs'
            }
            fragments.append(frag)

    return fragments
