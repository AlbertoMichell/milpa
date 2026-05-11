"""Normalización canónica de texto para indexación y consulta.

Este módulo centraliza el pre-procesado que aplican BM25 y la consulta para que
el resultado del retrieval sea estable frente a variaciones diacríticas, mayús-
culas/minúsculas y formas Unicode equivalentes.

Reglas:
  - NFC primero (combina decomposed → composed; necesario para textos OCR).
  - Eliminación de caracteres de control invisibles.
  - Preservación de los caracteres de palabra Unicode (incluye acentuados).
  - El folding ASCII y el stemming los realiza el analyzer Tantivy o Whoosh
    cuando está disponible; en backend de memoria se aplica unidecode.

Diseñado para ser barato (sin compilación de regex en cada llamada).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

try:
    from unidecode import unidecode  # type: ignore
except Exception:  # pragma: no cover - fallback
    unidecode = None  # type: ignore

_RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RE_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_RE_NEWLINES = re.compile(r"\n{3,}")


def normalize_unicode(text: Optional[str]) -> str:
    """NFC + limpieza de controles + colapso de espacios.

    Mantiene los acentos y la ñ; pensado para almacenar/indexar sin perder
    semántica. Útil para preparar el texto antes de pasarlo al analyzer del
    motor BM25 o al embedding.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", str(text))
    t = _RE_CONTROL.sub(" ", t)
    t = _RE_MULTI_SPACE.sub(" ", t)
    t = _RE_NEWLINES.sub("\n\n", t)
    return t.strip()


def fold_ascii_lower(text: Optional[str]) -> str:
    """Lowercase + folding ASCII (sin acentos) + colapso de espacios.

    Reservar para backends que no exponen un analyzer multilingüe (memoria,
    Whoosh viejo). Convierte ``Maíz`` → ``maiz``, ``Café`` → ``cafe`` y
    ``Ñ`` → ``n``. Para Tantivy y Whoosh con stemmer registrado, NO usar este
    helper en la indexación; la cadena de filtros del analyzer hace mejor
    trabajo (también stemming).
    """
    if not text:
        return ""
    t = normalize_unicode(text)
    if unidecode is not None:
        return unidecode(t).lower()
    # Fallback puro Python: descomponer y descartar combinantes.
    decomposed = unicodedata.normalize("NFKD", t)
    out_chars = []
    for ch in decomposed:
        if unicodedata.combining(ch):
            continue
        out_chars.append(ch)
    return "".join(out_chars).lower()


# Token clases comunes; mantenerlas aquí evita reconstruir regex en otros módulos.
TOKEN_RE_LATIN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_]+", re.UNICODE)


def simple_tokens(text: str) -> list[str]:
    """Tokenización simple para backends de memoria (no se usa en Tantivy/Whoosh)."""
    if not text:
        return []
    return TOKEN_RE_LATIN.findall(text)
