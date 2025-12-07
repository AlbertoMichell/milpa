# milpa_ai_backend/core/extract/pipeline.py
# Tubería de extracción SPRINT 3–5:
# - Localiza el archivo por doc_id (requiere docs.stored_path).
# - Si PDF: extrae texto por página (PyMuPDF) y usa OCR (Tesseract) cuando falte texto.
# - Detección de tablas (Camelot) si está disponible.
# - Chunking token-aware (aprox) con solapamiento (desde settings).
# - Extracción de unidades físicas y normalización SI (pint).
# - Persiste 'fragments', 'tables' y 'table_cells'; actualiza 'docs.lang_original'.

from __future__ import annotations
import io
import os
import csv
import json
import hashlib
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

try:
    import camelot
except Exception:
    camelot = None  # opcional

from milpa_ai_backend.core.logic.db import get_conn
from milpa_ai_backend.core.config import settings
from milpa_ai_backend.core.extract.chunker import chunk_pages
from milpa_ai_backend.core.extract.units import extract_units

@dataclass
class ExtractOptions:
    ocr_missing_text: bool = True
    detect_tables: bool = True
    dpi: int = 300
    lang_hint: str = "spa+eng"
    ocr_max_pages: int = 0  # 0 = sin límite adicional

def _detect_lang_simple(sample: str) -> Optional[str]:
    """
    Detector rápido sin dependencias: heurístico por stopwords.
    Solo para etiquetar 'es' o 'en' de forma aproximada.
    """
    sample = (sample or "").lower()
    es = sum(w in sample for w in [" el ", " la ", " los ", " las ", " de ", " que ", " y ", " en ", " para ", " con "])
    en = sum(w in sample for w in [" the ", " and ", " of ", " to ", " in ", " for ", " on "])
    if es > en:
        return "es"
    if en > es:
        return "en"
    return None

def _read_txt(path: str) -> List[Tuple[int, str, str]]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return [(1, text, "native")]

def _read_docx(path: str) -> List[Tuple[int, str, str]]:
    from docx import Document  # lazy import
    doc = Document(path)
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paras)
    return [(1, text, "native")]

def _pdf_to_pages(path: str, opts: ExtractOptions) -> List[Tuple[int, str, str]]:
    pages: List[Tuple[int, str, str]] = []
    doc = fitz.open(path)
    total = len(doc)
    for i, page in enumerate(doc, start=1):
        # 1) Intento nativo
        txt = page.get_text("text")
        source = "native"
        # 2) Si no hay texto y OCR habilitado -> rasterizar y OCR
        if opts.ocr_missing_text and len((txt or "").strip()) < 10:
            if opts.ocr_max_pages and i > opts.ocr_max_pages:
                # Cortamos OCR adicional si excede el límite; guardamos vacío
                pass
            else:
                mat = fitz.Matrix(opts.dpi / 72.0, opts.dpi / 72.0)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                try:
                    txt = pytesseract.image_to_string(img, lang=opts.lang_hint)
                    source = "ocr"
                except Exception:
                    # fallback si idioma no instalado
                    txt = pytesseract.image_to_string(img)
                    source = "ocr"
        pages.append((i, txt or "", source))
    return pages

def _extract_tables_pdf(path: str) -> List[Dict[str, Any]]:
    if camelot is None:
        return []
    try:
        tables = camelot.read_pdf(path, flavor="lattice", pages="all")  # lattice requiere ghostscript
    except Exception:
        # Fallback: intenta 'stream'
        try:
            tables = camelot.read_pdf(path, flavor="stream", pages="all")
        except Exception:
            return []

    out: List[Dict[str, Any]] = []
    for t in tables:
        df = t.df  # pandas.DataFrame
        csv_str = df.to_csv(index=False, header=False)
        bbox = list(t._bbox) if hasattr(t, "_bbox") else None
        out.append(
            {
                "csv": csv_str,
                "bbox": bbox,
                "nrows": int(df.shape[0]),
                "ncols": int(df.shape[1]),
                "page": int(getattr(t, "page", 1)),
            }
        )
    return out

def _file_ext(path: str) -> str:
    return os.path.splitext(path.lower())[1]

def _compute_fragment_id(doc_id: str, idx: int) -> str:
    return f"{doc_id}:{idx:04d}"

def extract_document(doc_id: str, options: Optional[ExtractOptions] = None) -> Dict[str, Any]:
    opts = options or ExtractOptions(
        ocr_missing_text=True,
        detect_tables=True,
        dpi=300,
        lang_hint="spa+eng",
        ocr_max_pages=settings.OCR_MAX_PAGES or 0,
    )

    # 1) Localizar archivo
    with get_conn() as conn:
        c = conn.cursor()
        row = c.execute(
            "SELECT stored_path, source FROM docs WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
        if not row or not row[0]:
            raise FileNotFoundError(f"stored_path no disponible para doc_id={doc_id}")
        path, original_name = row[0], row[1]

    ext = _file_ext(path)
    if ext == ".pdf":
        pages = _pdf_to_pages(path, opts)
        page_texts = [(p, t) for (p, t, _src) in pages]
    elif ext == ".txt":
        pages = _read_txt(path)
        page_texts = [(p, t) for (p, t, _src) in pages]
    elif ext in (".docx",):
        pages = _read_docx(path)
        page_texts = [(p, t) for (p, t, _src) in pages]
    else:
        raise ValueError(f"Extensión no soportada para extracción: {ext}")

    # 2) Chunking token-aware (aprox)
    chunks = chunk_pages(
        page_texts,
        max_tokens=settings.CHUNK_SIZE,
        overlap_ratio=float(settings.CHUNK_OVERLAP),
    )

    # 3) Persistencia en BD
    frag_count = 0
    native_pages = sum(1 for (_p, _t, s) in pages if s == "native")
    ocr_pages = sum(1 for (_p, _t, s) in pages if s == "ocr")
    lang_guess = _detect_lang_simple(" ".join(t for (_p, t) in page_texts)[:5000])

    with get_conn() as conn:
        c = conn.cursor()
        # Limpieza previa (idempotente) — opcional
        c.execute("DELETE FROM fragments WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM tables WHERE doc_id=?", (doc_id,))
        c.execute(
            "DELETE FROM table_cells WHERE table_id IN (SELECT table_id FROM tables WHERE doc_id=?)",
            (doc_id,),
        )

        # Insertar FRAGMENTS
        for idx, (pstart, pend, ch_text) in enumerate(chunks, start=1):
            fragment_id = _compute_fragment_id(doc_id, idx)
            c.execute(
                """
                INSERT OR REPLACE INTO fragments
                (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end, text, text_es, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
                """,
                (
                    fragment_id,
                    doc_id,
                    fragment_id,
                    None,
                    pstart,
                    pend,
                    ch_text,
                    None,           # text_es: traducción futura (SPRINT 6)
                    "native+ocr",   # mixto a nivel de documento
                ),
            )
            frag_count += 1

        # Extraer y guardar tablas (opcional)
        tables_count = 0
        cells_count = 0
        if opts.detect_tables and ext == ".pdf":
            for t_idx, t in enumerate(_extract_tables_pdf(path), start=1):
                table_id = f"{doc_id}:T{t_idx:03d}"
                bbox_json = json.dumps(t["bbox"]) if t["bbox"] else None
                c.execute(
                    """
                    INSERT OR REPLACE INTO tables (table_id, doc_id, page, bbox, csv, schema)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        table_id,
                        doc_id,
                        t["page"],
                        bbox_json,
                        t["csv"],
                        None,
                    ),
                )
                tables_count += 1
                # Persistir celdas para cita fina
                reader = csv.reader(io.StringIO(t["csv"]))
                for r_idx, row in enumerate(reader):
                    for c_idx, cell in enumerate(row):
                        c.execute(
                            """
                            INSERT OR REPLACE INTO table_cells (table_id, row, col, text, bbox)
                            VALUES (?, ?, ?, ?, ?);
                            """,
                            (table_id, r_idx, c_idx, cell, None),
                        )
                        cells_count += 1

        # Marcar idioma detectado en docs
        if lang_guess:
            c.execute(
                "UPDATE docs SET lang_original=? WHERE doc_id=?",
                (lang_guess, doc_id),
            )

        conn.commit()

    # 4) Unidades (se devuelven como preview; si luego quieres, puedes persistirlas en una tabla propia)
    # Toma una muestra para no explotar en payloads enormes.
    sample_text = " ".join(t for (_p, t) in page_texts)[:20000]
    units_found = extract_units(sample_text)[:50]

    return {
        "doc_id": doc_id,
        "pages_total": len(page_texts),
        "pages_native": native_pages,
        "pages_ocr": ocr_pages,
        "fragments_inserted": frag_count,
        "tables_inserted": tables_count,
        "table_cells_inserted": cells_count,
        "lang_guess": lang_guess,
        "units_sample": units_found,
    }
