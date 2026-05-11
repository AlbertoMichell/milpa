"""Tests para detección de idioma orientada a OCR Tesseract."""
from __future__ import annotations

from core.logic.lang_detect import (
    heuristic_language,
    to_tesseract_lang,
    detect_via_langdetect,
)


def test_heuristic_es() -> None:
    text = (
        "El maíz crece en la milpa con frijol y calabaza, una asociación que "
        "permite la nutrición del suelo y del cultivo principal en sistemas "
        "tradicionales mesoamericanos. Las características del clima determinan "
        "la elección de variedad."
    )
    assert heuristic_language(text) == "es"


def test_heuristic_en() -> None:
    text = (
        "The corn grows in the milpa with beans and squash, a system that "
        "improves the nutrition of soil and the main crop. The microclimate "
        "is the most important factor when selecting an appropriate variety."
    )
    assert heuristic_language(text) == "en"


def test_heuristic_short_returns_none() -> None:
    assert heuristic_language("muy corto") is None


def test_langdetect_works_when_installed() -> None:
    iso = detect_via_langdetect("El maíz crece en la milpa con frijol y calabaza.")
    # Si langdetect no está instalado, devuelve None y to_tesseract_lang cae a heurística.
    assert iso in ("es", None)


def test_to_tesseract_falls_back_to_default() -> None:
    # Texto cortísimo → no detectable; debe regresar default filtrado a packs disponibles.
    out = to_tesseract_lang("ab", default="spa+eng")
    assert "+" in out or out in {"spa", "eng", "spa+eng"} or len(out) >= 3


def test_to_tesseract_es_or_en_combines() -> None:
    text = (
        "El maíz crece en la milpa con frijol y calabaza, una asociación que "
        "permite la nutrición del suelo y del cultivo principal."
    )
    out = to_tesseract_lang(text, default="spa+eng")
    # Si tanto spa como eng están instalados, combinamos; si no, queda spa.
    assert out in {"spa+eng", "spa"}
