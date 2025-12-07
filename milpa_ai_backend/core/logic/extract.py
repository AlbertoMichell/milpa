# milpa_ai_backend/core/logic/extract.py
# Extracción de texto (nativo + OCR) y tablas con persistencia en SQLite.

from __future__ import annotations

import io
import json
import uuid
from typing import Optional, List, Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# Importar enriquecimiento de entidades
from milpa_ai_backend.core.logic.enrichment import extract_entities

# Camelot es opcional; si falla import, deshabilita tablas.
try:
    import camelot
    _CAMELOT_OK = True
except Exception:
    _CAMELOT_OK = False


def _uuid() -> str:
    return uuid.uuid4().hex


def _read_page_text_native(page: fitz.Page) -> str:
    """Texto nativo del PDF usando PyMuPDF."""
    try:
        txt = page.get_text("text") or ""
    except Exception:
        txt = ""
    return txt.strip()


def _page_needs_ocr(native_text: str, threshold: int = 40) -> bool:
    """
    Heurística muy simple:
    - Si hay menos de 'threshold' caracteres útiles, considera página como "escaneada" → OCR.
    """
    cleaned = "".join(ch for ch in native_text if not ch.isspace())
    return len(cleaned) < threshold


def _ocr_page_image(page: fitz.Page, lang: str = "spa+eng", scale: float = 2.0) -> str:
    """
    Renderiza la página a imagen y ejecuta Tesseract.
    scale=2.0 ~ 288 DPI si la página es ~72 DPI base.
    """
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)  # sin canal alpha
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    text = pytesseract.image_to_string(img, lang=lang or "eng") or ""
    return text.strip()


def _chunk_text(text: str, chunk_size: int = 1200) -> List[str]:
    """
    Particiona el texto en fragmentos aproximados a 'chunk_size'.
    Intenta respetar saltos de párrafo.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    parts, buf = [], []
    current = 0
    # Divide por párrafos primero
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    for p in paras:
        if current + len(p) + 2 <= chunk_size:
            buf.append(p)
            current += len(p) + 2
        else:
            if buf:
                parts.append("\n\n".join(buf))
            buf = [p]
            current = len(p)
    if buf:
        parts.append("\n\n".join(buf))

    # Aún demasiado grandes → trocea por palabras
    final: List[str] = []
    for block in parts:
        if len(block) <= chunk_size:
            final.append(block)
            continue
        words = block.split()
        cur_words, cur_len = [], 0
        for w in words:
            if cur_len + len(w) + 1 > chunk_size and cur_words:
                final.append(" ".join(cur_words))
                cur_words, cur_len = [w], len(w)
            else:
                cur_words.append(w)
                cur_len += len(w) + 1
        if cur_words:
            final.append(" ".join(cur_words))
    return final


def _insert_fragment(cur, doc_id: str, page_no: int, text: str, source: str):
    """Inserta un fragmento por página o chunk con entidades extraídas."""
    fragment_id = _uuid()
    
    # Extraer entidades del texto del fragmento
    entities_list = []
    try:
        entities, _, _ = extract_entities(text)
        # Serializar entidades a JSON
        entities_list = [{"type": e.type, "value": e.value} for e in entities]
    except Exception as e:
        # Si falla extracción, continuar sin entidades
        print(f"Warning: No se pudieron extraer entidades del fragmento: {e}")
        entities_list = []
    
    entities_json = json.dumps(entities_list) if entities_list else None
    
    cur.execute(
        """
        INSERT OR REPLACE INTO fragments
        (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end, text, text_es, source, entities, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'));
        """,
        (
            fragment_id,
            doc_id,
            None,  # fragment_uid (si tu UI lo usa)
            None,  # section_id  (si tu UI lo usa)
            page_no,
            page_no,
            text,
            None,  # text_es (traducción, si aplica)
            source,  # 'native' | 'ocr'
            entities_json,  # entidades extraídas en formato JSON
        ),
    )


def _insert_table(cur, doc_id: str, page: int, csv_text: str, bbox: Optional[str], schema_obj: dict):
    """Inserta una tabla y sus celdas opcionalmente."""
    table_id = _uuid()
    cur.execute(
        """
        INSERT OR REPLACE INTO tables
        (table_id, doc_id, page, bbox, csv, schema)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (table_id, doc_id, page, bbox, csv_text, json.dumps(schema_obj) if schema_obj else None),
    )
    return table_id


def _insert_table_cells(cur, table_id: str, df):
    """Guarda celdas por (row, col) con el texto (bbox no disponible con camelot por defecto)."""
    for r_idx in range(len(df.index)):
        for c_idx, col_name in enumerate(df.columns):
            val = df.iat[r_idx, c_idx]
            cur.execute(
                """
                INSERT OR REPLACE INTO table_cells
                (table_id, row, col, text, bbox)
                VALUES (?, ?, ?, ?, ?);
                """,
                (table_id, r_idx, c_idx, "" if val is None else str(val), None),
            )


def extract_document(
    conn,
    doc_id: str,
    pdf_path: str,
    ocr_missing_text: bool = True,
    extract_tables: Optional[str] = "auto",
    chunk_size: int = 1200,
    lang: str = "spa+eng",
) -> dict:
    """
    Procesa el PDF:
      - Extrae texto (nativo y/u OCR por página) → fragments.
      - Extrae tablas (Camelot) → tables y table_cells.
    Retorna contadores y páginas totales.
    """
    cur = conn.cursor()

    # --- Texto (nativo / OCR) ---
    doc = fitz.open(pdf_path)
    fragments_written = 0
    for i in range(doc.page_count):
        page = doc.load_page(i)
        page_no = i + 1

        native = _read_page_text_native(page)
        use_ocr = ocr_missing_text and _page_needs_ocr(native)
        final_text = native

        source = "native"
        if use_ocr:
            try:
                final_text = _ocr_page_image(page, lang=lang)
                source = "ocr"
            except Exception:
                # Si OCR falla, conserva lo nativo aunque sea poco
                final_text = native
                source = "native"

        # chunking
        for chunk in _chunk_text(final_text, chunk_size=chunk_size):
            try:
                _insert_fragment(cur, doc_id, page_no, chunk, source)
                fragments_written += 1
                print(f"[DEBUG] Fragment inserted: page={page_no}, len={len(chunk)}")
            except Exception as e:
                print(f"[ERROR] Failed to insert fragment: {e}")
                import traceback
                traceback.print_exc()

    # --- Tablas (Camelot) ---
    tables_written = 0
    if _CAMELOT_OK and (extract_tables is None or extract_tables.lower() != "none"):
        flavors: List[str]
        mode = (extract_tables or "auto").lower()
        if mode == "lattice":
            flavors = ["lattice"]
        elif mode == "stream":
            flavors = ["stream"]
        elif mode in ("lattice+stream", "stream+lattice"):
            flavors = ["lattice", "stream"]
        else:
            flavors = ["lattice", "stream"]  # auto: intenta ambos

        seen = 0
        for flavor in flavors:
            try:
                tables = camelot.read_pdf(pdf_path, pages="all", flavor=flavor)
            except Exception:
                continue
            for t in tables:
                df = t.df
                csv_text = df.to_csv(index=False, header=True)
                schema_obj = {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1]), "flavor": flavor}
                table_id = _insert_table(cur, doc_id, getattr(t, "page", None) or 0, csv_text, None, schema_obj)
                _insert_table_cells(cur, table_id, df)
                tables_written += 1
            seen += len(tables)
            # si ya capturamos tablas con el primer flavor, puedes decidir no seguir
            # aquí seguimos para combinar ambos sabores

    return {
        "pages": doc.page_count,
        "fragments_written": fragments_written,
        "tables_written": tables_written,
    }
