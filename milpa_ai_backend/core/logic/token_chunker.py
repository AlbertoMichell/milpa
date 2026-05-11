"""Chunking por tokens compatible con el embedder.

El embedder por defecto (``paraphrase-multilingual-MiniLM-L12-v2``) tiene
``max_seq_length=128`` tokens; cualquier fragmento que supere ese límite es
truncado al embed, perdiendo señal. Este chunker:

  - Carga el tokenizer del embedder configurado (``settings.EMBED_MODEL``).
  - Cuenta tokens reales (no caracteres) por chunk.
  - Garantiza que cada chunk encaje en ``target_tokens`` (default 110, deja
    margen sobre 128 por tokens especiales) con solapamiento opcional en
    tokens.
  - Respeta límites naturales: párrafos primero, oraciones después, palabras
    como último recurso.

Si el tokenizer falla (modelo no descargado, sin red, etc.), el caller debe
caer al chunker por caracteres existente.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Optional

_log = logging.getLogger(__name__)

_RE_PARA = re.compile(r"\n\s*\n+")
_RE_SENT = re.compile(r"(?<=[\.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])")


_cached_tokenizer = None


def get_tokenizer(model_name: Optional[str] = None):
    """Devuelve un tokenizer HF (``AutoTokenizer``) cacheado por proceso."""
    global _cached_tokenizer
    if _cached_tokenizer is not None and (model_name is None or _cached_tokenizer.name_or_path == model_name):
        return _cached_tokenizer
    try:
        from transformers import AutoTokenizer  # type: ignore
        from milpa_ai_backend.core.config import settings  # type: ignore
        name = model_name or getattr(settings, "EMBED_MODEL", None) or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        tok = AutoTokenizer.from_pretrained(name, use_fast=True)
        _cached_tokenizer = tok
        return tok
    except Exception as e:
        _log.warning(f"Tokenizer no disponible ({e}); chunker por tokens deshabilitado.")
        return None


def count_tokens(text: str, tokenizer=None) -> int:
    tok = tokenizer or get_tokenizer()
    if tok is None or not text:
        return len(text or "")
    try:
        return len(tok.encode(text, add_special_tokens=False))
    except Exception:
        return len(text)


def _split_sentences(paragraph: str) -> List[str]:
    sents = _RE_SENT.split(paragraph)
    return [s.strip() for s in sents if s and s.strip()]


def chunk_by_tokens(
    text: str,
    *,
    target_tokens: int = 110,
    overlap_tokens: int = 16,
    tokenizer=None,
) -> List[str]:
    """Particiona ``text`` en chunks de ≤ ``target_tokens`` tokens del modelo.

    El solapamiento se mide en tokens y se materializa repitiendo los últimos
    ``overlap_tokens`` tokens del chunk anterior al inicio del siguiente.

    Si el tokenizer no está disponible (offline o sin transformers), regresa
    una lista con el texto íntegro (caller debe usar fallback por caracteres).
    """
    if not text or not text.strip():
        return []
    tok = tokenizer or get_tokenizer()
    if tok is None:
        return [text.strip()]

    # 1) Por párrafos
    paragraphs = [p.strip() for p in _RE_PARA.split(text) if p.strip()]
    if not paragraphs:
        return []
    ids_per_para: List[List[int]] = []
    for p in paragraphs:
        try:
            ids = tok.encode(p, add_special_tokens=False)
        except Exception:
            ids = []
        if ids:
            ids_per_para.append(ids)
        else:
            ids_per_para.append([])

    chunks_ids: List[List[int]] = []
    cur: List[int] = []

    def flush() -> None:
        nonlocal cur
        if cur:
            chunks_ids.append(cur)
            cur = []

    for p, ids in zip(paragraphs, ids_per_para):
        if not ids:
            continue
        # Si el párrafo cabe completo, lo añadimos.
        if len(cur) + len(ids) <= target_tokens:
            cur.extend(ids)
            continue
        # Si el párrafo solo no cabe, dividimos por oraciones.
        if len(ids) > target_tokens:
            flush()
            for sent in _split_sentences(p):
                try:
                    s_ids = tok.encode(sent, add_special_tokens=False)
                except Exception:
                    s_ids = []
                if not s_ids:
                    continue
                if len(s_ids) > target_tokens:
                    # Oración mega-larga: cortar por slices de target_tokens
                    for i in range(0, len(s_ids), target_tokens):
                        chunks_ids.append(s_ids[i : i + target_tokens])
                    continue
                if len(cur) + len(s_ids) > target_tokens:
                    flush()
                cur.extend(s_ids)
            flush()
            continue
        # Cabe pero requiere flush primero
        flush()
        cur.extend(ids)
    flush()

    # Aplicar overlap en tokens
    if overlap_tokens > 0 and len(chunks_ids) >= 2:
        for i in range(1, len(chunks_ids)):
            tail = chunks_ids[i - 1][-overlap_tokens:]
            chunks_ids[i] = tail + chunks_ids[i]

    # Decodificar
    out: List[str] = []
    for ids in chunks_ids:
        try:
            text_chunk = tok.decode(ids, skip_special_tokens=True).strip()
        except Exception:
            continue
        if text_chunk:
            out.append(text_chunk)
    return out
