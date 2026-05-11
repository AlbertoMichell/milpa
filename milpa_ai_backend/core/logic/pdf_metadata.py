# milpa_ai_backend/core/logic/pdf_metadata.py
# Complementa metadatos al ingerir PDF: PyMuMPDF /info dict + fecha.
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

_PDF_DATE_YEAR = re.compile(r"^D:(\d{4})")


def _parse_pdf_year(creation: Optional[str], mod: Optional[str]) -> Optional[int]:
    for s in (creation, mod):
        if not s:
            continue
        m = _PDF_DATE_YEAR.match(s.strip())
        if m:
            y = int(m.group(1))
            if 1980 <= y <= 2100:
                return y
    return None


def suggest_from_pdf_path(pdf_path: str | Path) -> Dict[str, Any]:
    """
    Lee diccionario de metadatos del PDF (sin abrir 2 veces al insertar: solo para rellenar huecos).
    """
    p = Path(pdf_path)
    if not p.exists() or p.suffix.lower() != ".pdf":
        return {}

    import fitz  # PyMuPDF (ya dependencia de extract)

    doc = fitz.open(p)
    try:
        meta = doc.metadata or {}
    finally:
        doc.close()

    title = (meta.get("title") or "").strip() or None
    author = (meta.get("author") or "").strip() or None
    year = _parse_pdf_year(meta.get("creationDate"), meta.get("modDate"))
    if author and author.lower() in ("usuario", "user", "author"):
        # Metadato genérico de Word: no aporta nombre real
        author = None
    return {"title": title, "author": author, "year": year}


def suggest_lang_from_text_snippet(text: str) -> Optional[str]:
    """
    Heurística ligera (sin depender de langdetect): si hay suficiente español típico, 'es'.
    """
    if not text or len(text) < 80:
        return None
    t = text.lower()
    # Palabras/acentos frecuentes en español de documentos técnicos
    markers = (
        "el ", "la ", " de ", " los ", " las ", " y ", " una ", " para ", " con ",
        "ión", "ción", "ación", " del ", " al ", " es ", " en ", "se ", " que ",
    )
    score = sum(1 for m in markers if m in t)
    if score >= 4:
        return "es"
    return None
