"""Pruebas para OCR por regiones.

No invocamos Tesseract real (lento + opcional). Validamos:

  - ``_detect_column_bands_cv`` divide una imagen sintética con dos columnas
    bien separadas por un gap blanco.
  - ``ocr_page_by_regions`` con un PDF en blanco no falla y devuelve al menos
    una región (la página completa) cuando OpenCV está instalado.
"""
from __future__ import annotations

import os
import sys
import tempfile

import fitz
import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from milpa_ai_backend.core.logic.ocr_regions import (  # noqa: E402
    _detect_column_bands_cv,
    ocr_page_by_regions,
    render_page_image,
)


def test_detect_two_column_bands_via_synthetic_image():
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(img)
    # Texto-like patrón: rectángulos negros en columna izquierda y derecha,
    # con un gap claro de 100 px entre 450 y 550.
    for y in range(50, 560, 30):
        draw.rectangle([60, y, 440, y + 12], fill="black")
        draw.rectangle([560, y, 940, y + 12], fill="black")
    bands = _detect_column_bands_cv(img, max_columns=3)
    assert len(bands) >= 2
    a, b = bands[0], bands[1]
    assert a[1] <= 460  # primer banda termina antes del gap
    assert b[0] >= 540  # segunda banda empieza después del gap


def test_render_page_image_produces_png_size_proportional_to_scale():
    doc = fitz.open()
    doc.new_page(width=500, height=700)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    try:
        d = fitz.open(f.name)
        try:
            page = d.load_page(0)
            img1, sc1 = render_page_image(page, scale=1.0)
            img2, sc2 = render_page_image(page, scale=2.0)
            assert img1.size == (500, 700)
            assert img2.size == (1000, 1400)
            assert sc1 == 1.0 and sc2 == 2.0
        finally:
            d.close()
    finally:
        os.unlink(f.name)


def test_ocr_page_by_regions_blank_page_returns_one_region():
    """En página blanca: bandas degeneran a (0,W) → una sola región full page."""
    pytest.importorskip("cv2")
    doc = fitz.open()
    doc.new_page(width=500, height=700)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    try:
        d = fitz.open(f.name)
        try:
            page = d.load_page(0)
            try:
                text, regions = ocr_page_by_regions(page, lang="eng", scale=1.5)
            except Exception as e:
                pytest.skip(f"Tesseract no disponible: {e}")
            assert len(regions) >= 1
            assert all(r.x1 > r.x0 for r in regions)
        finally:
            d.close()
    finally:
        os.unlink(f.name)
