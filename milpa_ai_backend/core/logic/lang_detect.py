"""Detección de idioma para configurar Tesseract dinámicamente.

Estrategia en cascada (de más a menos confiable):
  1. ``langdetect`` si está instalado (probabilístico).
  2. Heurística por marcadores léxicos (es / en / pt / fr).
  3. Default ``spa+eng``.

El resultado se traduce al formato Tesseract (ej. ``spa``, ``eng``,
``spa+eng``, ``fra``, ``por``). Validamos contra los idiomas instalados con
``pytesseract.get_languages()`` (cacheado) para no pasar paquetes ausentes.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Set

_log = logging.getLogger(__name__)

# Mapeo ISO-639-1 → código Tesseract (ISO-639-2)
_ISO_TO_TESS = {
    "es": "spa",
    "en": "eng",
    "pt": "por",
    "fr": "fra",
    "it": "ita",
    "de": "deu",
    "ca": "cat",
    "gl": "glg",
}

# Marcadores léxicos por idioma (palabras frecuentes y diacríticos)
_MARKERS = {
    "es": (
        "el ", "la ", " de ", " los ", " las ", " y ", " una ", " para ", " con ",
        "ión", "ción", "ación", " del ", " al ", " es ", " en ", "se ", " que ",
        " no ", " por ", "ñ", "á", "é", "í", "ó", "ú",
    ),
    "en": (
        " the ", " and ", " of ", " to ", " in ", " is ", " that ", " for ",
        " with ", " as ", " on ", " by ", " be ", " this ", " an ",
    ),
    "pt": (
        " o ", " a ", " os ", " as ", " de ", " do ", " da ", " que ", " não ",
        "ção", "ões", "ã", "õ",
    ),
    "fr": (
        " le ", " la ", " les ", " de ", " des ", " du ", " et ", " un ", " une ",
        " que ", "œ", "ç", "à", "é", "è", "ê",
    ),
}


_cached_tess_langs: Optional[Set[str]] = None


def available_tesseract_langs() -> Set[str]:
    """Devuelve el conjunto de idiomas disponibles en la instalación local.

    Cacheado: se llama una sola vez por proceso. Si ``pytesseract`` no está o
    Tesseract no está instalado, devuelve un set vacío y dejamos que el caller
    haga fallback al default (``spa+eng``).
    """
    global _cached_tess_langs
    if _cached_tess_langs is not None:
        return _cached_tess_langs
    langs: Set[str] = set()
    try:
        import pytesseract
        langs = set(pytesseract.get_languages(config="") or [])
    except Exception as e:
        _log.debug(f"available_tesseract_langs falló: {e}")
    _cached_tess_langs = langs
    return langs


def heuristic_language(text: str) -> Optional[str]:
    """Devuelve código ISO-639-1 (``es``/``en``/``pt``/``fr``) o ``None``.

    Cuenta marcadores léxicos en la muestra y devuelve el lenguaje con mayor
    score si supera un umbral mínimo (4 hits) y al menos doble del segundo
    candidato.
    """
    if not text or len(text) < 80:
        return None
    t = text.lower()
    scores = {lang: sum(1 for m in markers if m in t) for lang, markers in _MARKERS.items()}
    ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranking or ranking[0][1] < 4:
        return None
    if len(ranking) >= 2 and ranking[0][1] < ranking[1][1] * 2:
        # Caso ambiguo: español + inglés muy mezclado, devolvemos None para
        # dejar que el caller use spa+eng combinado.
        return None
    return ranking[0][0]


def detect_via_langdetect(text: str) -> Optional[str]:
    try:
        from langdetect import detect, DetectorFactory  # type: ignore
        DetectorFactory.seed = 0
        if not text or len(text) < 80:
            return None
        return detect(text[:4000])
    except Exception:
        return None


def to_tesseract_lang(text: str, default: str = "spa+eng") -> str:
    """Devuelve el lang string adecuado para ``pytesseract.image_to_string``.

    Si la detección no es concluyente o el idioma no está instalado, regresa
    al ``default`` (que combina español + inglés por ser el escenario más
    frecuente del corpus MILPA).
    """
    available = available_tesseract_langs()
    iso = detect_via_langdetect(text) or heuristic_language(text)
    if not iso:
        return _filter_available(default, available)
    tess = _ISO_TO_TESS.get(iso)
    if not tess:
        return _filter_available(default, available)
    if available and tess not in available:
        # No está el paquete instalado: caer a default.
        return _filter_available(default, available)
    # Si es ES o EN, combinamos con el otro para textos mixtos típicos.
    if iso in ("es", "en") and "spa" in available and "eng" in available:
        return "spa+eng"
    return tess


def _filter_available(lang_str: str, available: Set[str]) -> str:
    """Si una lengua del default no está instalada, la quita.

    Ej: en una máquina sin ``spa`` instalado, ``spa+eng`` cae a ``eng``.
    """
    if not available:
        return lang_str
    parts = [p for p in lang_str.split("+") if p in available]
    if not parts:
        # Si nada del default está disponible, regresamos al primer instalado.
        return next(iter(available))
    return "+".join(parts)


def detect_iso(text: str) -> Optional[str]:
    """Devuelve solo el código ISO-639-1 (para metadata.lang_original)."""
    return detect_via_langdetect(text) or heuristic_language(text)
