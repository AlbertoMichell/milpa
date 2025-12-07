# milpa_ai_backend/core/logic/ocr.py
# ------------------------------------------------------------
# OCR:
#   - needs_ocr(coverage, dsi): heurística para decidir si una página requiere OCR.
#   - render_pdf_page_image: rasteriza la página a PNG (dpi ajustable).
#   - run_tesseract_image: corre Tesseract y devuelve texto + "quality" proxy.
#   - ocr_pdf_pages: aplica OCR a un conjunto de páginas y retorna dict por página.
# Notas:
#   * Para CER/WER reales se necesita ground-truth; aquí exponemos un proxy:
#     quality = mean_confidence/100 (si el motor provee confidencias).
# ------------------------------------------------------------
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import io

# Imports opcionales
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import pytesseract
except Exception:
    pytesseract = None


def needs_ocr(coverage: float, dsi: float) -> bool:
    """
    Heurística: si hay baja cobertura de spans de texto o pobre estructura,
    conviene intentar OCR.
    """
    return (coverage is not None and coverage < 0.15) or (dsi is not None and dsi < 0.85)


def render_pdf_page_image(path: str, page_number: int, dpi: int = 300) -> bytes:
    """
    Rasteriza una página de PDF a imagen PNG. Retorna bytes de PNG.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF requerido para rasterizar páginas PDF.")
    doc = fitz.open(path)
    p = doc[page_number - 1]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = p.get_pixmap(matrix=mat, alpha=False)  # sin canal alpha para Tesseract
    return pix.tobytes("png")


def run_tesseract_image(image_bytes: bytes, lang: str = "spa+eng") -> Dict[str, Any]:
    """
    Ejecuta OCR con Tesseract. Retorna:
      - text: texto extraído,
      - ocr_quality: [0..1] (proxy por confidencia media),
      - cer/wer: None (placeholders; requieren ground truth).
    """
    if pytesseract is None or Image is None:
        raise RuntimeError("pytesseract y Pillow son necesarios para OCR.")

    img = Image.open(io.BytesIO(image_bytes))
    # Extrae datos con confidencias por palabra
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    words = data.get("text", []) or []
    confs = data.get("conf", []) or []

    # Texto consolidado
    text = " ".join(w for w in words if isinstance(w, str) and w.strip())

    # Confidencia media (ignora -1)
    valid = [float(c) for c in confs if isinstance(c, (int, float, str)) and str(c).isdigit()]
    mean_conf = (sum(valid) / len(valid)) if valid else 0.0
    quality = max(0.0, min(mean_conf / 100.0, 1.0))

    return {"text": text, "ocr_quality": round(quality, 4), "cer": None, "wer": None}


def ocr_pdf_pages(path: str, pages: List[int], lang: str = "spa+eng") -> Dict[int, Dict[str, Any]]:
    """
    Aplica OCR a una lista de páginas (1-indexed). Retorna un dict:
      { page_number: {"text":..., "ocr_quality":..., "cer":..., "wer":...}, ... }
    """
    results: Dict[int, Dict[str, Any]] = {}
    for p in pages:
        png = render_pdf_page_image(path, p, dpi=300)
        results[p] = run_tesseract_image(png, lang=lang)
    return results
