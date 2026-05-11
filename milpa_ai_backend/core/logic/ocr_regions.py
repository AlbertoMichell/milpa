"""OCR por regiones para páginas escaneadas multi-columna.

Cuando la página viene **sin texto nativo** (PDF escaneado), no hay bloques
PyMuPDF para guiar el orden de lectura. La heurística de columnas tradicional
se basa en el texto extraído, así que falla. Este módulo construye la
detección directamente sobre la imagen rasterizada:

  1. Render de la página a imagen RGB con escala configurable (288 DPI).
  2. Binarización (Otsu) y proyección horizontal de píxeles oscuros.
  3. Buscamos "valles" (columnas con poca tinta) que persisten verticalmente:
     son los espacios entre columnas reales.
  4. Para cada banda detectada (columna), recortamos un ROI y corremos
     Tesseract con varios PSM eligiendo la mejor salida por ``_useful_chars``.
  5. Ensamblamos las salidas en orden de lectura y devolvemos también los
     bboxes de cada columna en coordenadas del PDF.

Si OpenCV no está disponible, se cae al OCR de página completa (comportamiento
previo). El caller (``extract.py``) solo cambia entre ``ocr_full_page`` y
``ocr_by_regions`` según el número de regiones detectadas y la cobertura.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

_log = logging.getLogger(__name__)


@dataclass
class OCRRegion:
    """Resultado de OCR sobre un ROI de la página."""
    text: str
    # bbox en coordenadas PDF (puntos)
    x0: float
    y0: float
    x1: float
    y1: float
    psm_used: int = 6


def _useful_chars(s: str) -> int:
    return sum(1 for ch in s if ch.isalnum())


def _ocr_image(img: Image.Image, lang: str) -> Tuple[str, int]:
    """Devuelve (mejor_texto, psm_usado) probando psm 6/4/3."""
    import pytesseract
    best_text = ""
    best_psm = 6
    best_score = -1
    for psm in (6, 4, 3):
        try:
            txt = pytesseract.image_to_string(
                img,
                lang=lang or "eng",
                config=f"--psm {psm} --oem 3 -c preserve_interword_spaces=1",
            ) or ""
        except Exception:
            try:
                txt = pytesseract.image_to_string(img, lang=lang or "eng") or ""
            except Exception:
                continue
        score = _useful_chars(txt)
        if score > best_score:
            best_score = score
            best_text = txt
            best_psm = psm
    return best_text, best_psm


def _detect_column_bands_cv(
    img_pil: Image.Image,
    *,
    min_gap_ratio: float = 0.06,
    min_band_ratio: float = 0.10,
    max_columns: int = 3,
) -> List[Tuple[int, int]]:
    """Devuelve [(x_left, x_right), ...] en píxeles para cada columna detectada.

    Estrategia: binarizamos con Otsu (texto = oscuro), tomamos la suma vertical
    de píxeles de tinta (proyección horizontal) y suavizamos. Buscamos
    "valles" que cumplan:
      - profundidad: < 3% del máximo de la proyección suavizada;
      - ancho: ≥ ``min_gap_ratio * page_width``;
      - posición: no en los márgenes (>=5% desde cada borde).
    Cada par de valles separa columnas.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    img = np.array(img_pil.convert("L"))  # gris 0..255
    h, w = img.shape
    if w < 200 or h < 200:
        return [(0, w)]
    # Binarización inversa (texto = blanco sobre fondo negro tras Otsu inverso).
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    proj = bw.sum(axis=0).astype("float64") / 255.0  # cuenta de píxeles de tinta por columna
    # Suavizamos con kernel del tamaño 1.5% del ancho para eliminar ruido.
    k = max(int(w * 0.015), 5)
    if k % 2 == 0:
        k += 1
    kernel = np.ones(k) / k
    proj = np.convolve(proj, kernel, mode="same")
    if proj.max() <= 0:
        return [(0, w)]
    # Umbral: 6% del máximo es "casi blanco" (no hay tinta) — se considera valle.
    thresh = proj.max() * 0.06
    in_valley = proj < thresh
    # Extraemos rangos de valles
    valleys: List[Tuple[int, int]] = []
    i = 0
    margin = int(w * 0.05)
    while i < w:
        if in_valley[i]:
            j = i
            while j < w and in_valley[j]:
                j += 1
            x_a, x_b = i, j
            # Filtramos márgenes y huecos demasiado finos
            if x_a > margin and x_b < (w - margin) and (x_b - x_a) >= int(w * min_gap_ratio):
                valleys.append((x_a, x_b))
            i = j
        else:
            i += 1
    if not valleys:
        return [(0, w)]
    valleys.sort(key=lambda r: r[1] - r[0], reverse=True)
    valleys = valleys[: max_columns - 1]
    valleys.sort(key=lambda r: r[0])
    bands: List[Tuple[int, int]] = []
    prev = 0
    for v0, v1 in valleys:
        bands.append((prev, v0))
        prev = v1
    bands.append((prev, w))
    # Validamos que cada banda tenga un mínimo de ancho relativo
    bands = [(a, b) for (a, b) in bands if (b - a) >= int(w * min_band_ratio)]
    if not bands:
        return [(0, w)]
    return bands


def render_page_image(page: fitz.Page, scale: float = 4.0) -> Tuple[Image.Image, float]:
    """Renderiza la página a imagen y devuelve ``(img, scale)``."""
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img, scale


def ocr_page_by_regions(
    page: fitz.Page,
    *,
    lang: str,
    scale: float = 4.0,
    max_columns: int = 3,
) -> Tuple[str, List[OCRRegion]]:
    """OCR multi-columna: detecta columnas en la imagen y aplica Tesseract por ROI.

    Devuelve ``(texto_concatenado, regiones)``. ``regiones`` lleva bbox en
    coordenadas PDF (puntos), útil para persistir como bbox de fragmento al
    extractor.
    """
    img, sc = render_page_image(page, scale=scale)
    bands = _detect_column_bands_cv(img, max_columns=max_columns)
    page_w = float(page.rect.width or img.width / sc)
    page_h = float(page.rect.height or img.height / sc)
    regions: List[OCRRegion] = []
    text_pieces: List[str] = []
    if not bands or len(bands) == 1:
        # Sin multi-col detectada → OCR full page (mantiene compatibilidad).
        text, psm = _ocr_image(img, lang)
        regions.append(
            OCRRegion(text=text, x0=0.0, y0=0.0, x1=page_w, y1=page_h, psm_used=psm)
        )
        return text, regions

    for (x_a, x_b) in bands:
        roi = img.crop((x_a, 0, x_b, img.height))
        text, psm = _ocr_image(roi, lang)
        # Coordenadas PDF del ROI: dividir por scale.
        x0 = x_a / sc
        x1 = x_b / sc
        regions.append(
            OCRRegion(text=text, x0=x0, y0=0.0, x1=x1, y1=page_h, psm_used=psm)
        )
        text_pieces.append(text)
    full = "\n\n".join(text_pieces)
    return full, regions
