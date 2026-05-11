# milpa_ai_backend/core/logic/extract.py
# Extracción de texto (nativo + OCR) y tablas con persistencia en SQLite.

from __future__ import annotations

import io
import json
import re
import uuid
from typing import Optional, List, Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

# Importar enriquecimiento de entidades
from milpa_ai_backend.core.logic.enrichment import extract_entities
from milpa_ai_backend.core.config import settings as _settings
from milpa_ai_backend.core.logic.extract_layout import (
    apply_chunk_overlap,
    read_page_text_layout_aware,
    pick_best_native_text,
    strip_repeating_page_lines,
    normalize_extracted_text,
)
from milpa_ai_backend.core.logic.lang_detect import to_tesseract_lang
from milpa_ai_backend.core.logic.blocks import (
    Block,
    PageBlocks,
    page_blocks,
    union_bbox,
    group_blocks_into_chunks,
    collect_lines,
    subdivide_lines_by_chars,
    union_line_bbox,
)
from milpa_ai_backend.core.logic.ocr_regions import ocr_page_by_regions
from milpa_ai_backend.core.logic.token_chunker import (
    chunk_by_tokens,
    get_tokenizer,
    count_tokens,
)

# Camelot es opcional; si falla import, deshabilita tablas.
try:
    import camelot
    _CAMELOT_OK = True
except Exception:
    _CAMELOT_OK = False


def _uuid() -> str:
    return uuid.uuid4().hex


def _read_page_text_sort_only(page: fitz.Page) -> str:
    """Solo get_text con sort (baseline rápido)."""
    try:
        try:
            txt = page.get_text("text", sort=True) or ""
        except (TypeError, Exception):
            txt = page.get_text("text") or ""
    except Exception:
        txt = ""
    return normalize_extracted_text(txt)


def _read_page_text_native(
    page: fitz.Page, *, use_layout: bool = True
) -> str:
    """
    Texto nativo: layout por bbox (dict) + sort como respaldo, elige el más fiable.
    """
    t_sort = _read_page_text_sort_only(page)
    if not use_layout:
        return t_sort
    t_layout = read_page_text_layout_aware(page)
    return pick_best_native_text(page, t_sort, t_layout)


def _page_needs_ocr(native_text: str, threshold: int = 40) -> bool:
    """
    Heurística muy simple:
    - Si hay menos de 'threshold' caracteres útiles, considera página como "escaneada" → OCR.
    """
    cleaned = "".join(ch for ch in native_text if not ch.isspace())
    return len(cleaned) < threshold


def _useful_chars(s: str) -> int:
    """Cuenta caracteres útiles (letras o dígitos) — heurística para comparar OCR."""
    return sum(1 for ch in s if ch.isalnum())


def _page_bbox(page: "fitz.Page") -> Optional[str]:
    """Bbox que cubre todo el contenido textual de la página (JSON)."""
    try:
        d = page.get_text("dict") or {}
    except Exception:
        return None
    xs1: list[float] = []
    ys1: list[float] = []
    xs2: list[float] = []
    ys2: list[float] = []
    for block in d.get("blocks", []) or []:
        if block.get("type") != 0:
            continue
        bb = block.get("bbox")
        if not bb or len(bb) < 4:
            continue
        xs1.append(float(bb[0]))
        ys1.append(float(bb[1]))
        xs2.append(float(bb[2]))
        ys2.append(float(bb[3]))
    if not xs1:
        return None
    return json.dumps([min(xs1), min(ys1), max(xs2), max(ys2)])


def _detect_doc_lang_for_ocr(doc: "fitz.Document") -> str:
    """Examina el texto nativo de hasta 3 páginas para sugerir el lang OCR.

    Si el documento es 100% escaneado (sin texto nativo en ninguna página),
    devolvemos el default ``spa+eng`` filtrado a los packs instalados.
    """
    sample_chunks: list[str] = []
    pages_to_check = min(doc.page_count, 3)
    for i in range(pages_to_check):
        try:
            txt = doc.load_page(i).get_text("text") or ""
        except Exception:
            continue
        if txt.strip():
            sample_chunks.append(txt[:1500])
        if sum(len(x) for x in sample_chunks) > 2500:
            break
    sample = "\n".join(sample_chunks).strip()
    return to_tesseract_lang(sample, default="spa+eng")


def _table_signature(df) -> str:
    """Hash estable para deduplicar tablas detectadas por flavors distintos.

    Camelot lattice y stream pueden detectar la misma tabla con cabeceras o
    filas ligeramente distintas; firmamos por (n_rows, n_cols, primeras 10
    celdas no vacías) para descartar copias quasi-idénticas.
    """
    try:
        import hashlib
        sample: list[str] = []
        for r in range(min(int(df.shape[0]), 8)):
            for c in range(min(int(df.shape[1]), 4)):
                v = df.iat[r, c]
                if v is None:
                    continue
                s = re.sub(r"\s+", " ", str(v)).strip().lower()
                if s:
                    sample.append(s)
                if len(sample) >= 16:
                    break
            if len(sample) >= 16:
                break
        key = f"{df.shape[0]}x{df.shape[1]}|" + "|".join(sample)
        return hashlib.sha1(key.encode("utf-8")).hexdigest()
    except Exception:
        return _uuid()


def _ocr_page_image(page: fitz.Page, lang: str = "spa+eng", scale: float = 2.0) -> str:
    """
    Renderiza la página a imagen y ejecuta Tesseract con varios PSM, eligiendo
    la salida con más caracteres útiles. Esto cubre tres escenarios típicos:

      - psm=6: bloque de texto único (ideal para una columna llena con OCR
        ruidoso).
      - psm=4: una columna de texto de ancho variable (mejor cuando hay
        encabezados grandes o pies grandes).
      - psm=3: detección automática (default, sirve para layouts mixtos).

    También soporta detección de idioma robusta: usa ``lang`` por defecto, con
    fallback al primer idioma disponible si tesseract no encuentra el dato.
    """
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)  # sin canal alpha
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    candidates: List[str] = []
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
        candidates.append(txt)

    if not candidates:
        return ""
    best = max(candidates, key=_useful_chars)
    return normalize_extracted_text(best)


def _pack_lines_to_chunks(text: str, chunk_size: int) -> List[str]:
    """
    Word/PDFs con una sola caja: muchos \\n y pocos \\n\\n. Parte líneas largas por
    palabras, luego agrupa líneas hasta chunk_size.
    """
    raw = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not raw:
        return []
    lines: List[str] = []
    for ln in raw:
        if len(ln) <= chunk_size:
            lines.append(ln)
        else:
            lines.extend(_chunk_by_words_if_needed(ln, chunk_size))
    if not lines:
        return []
    out, buf, n = [], [], 0
    for ln in lines:
        add = n + (1 if buf else 0) + len(ln)
        if add <= chunk_size or not buf:
            buf.append(ln)
            n = add
        else:
            out.append("\n".join(buf))
            buf, n = [ln], len(ln)
    if buf:
        out.append("\n".join(buf))
    return [o for o in out if o.strip()]


def _chunk_by_words_if_needed(block: str, chunk_size: int) -> List[str]:
    block = block.strip()
    if len(block) <= chunk_size:
        return [block]
    words = block.split()
    out, cur_words, cur_len = [], [], 0
    for w in words:
        if cur_len + len(w) + 1 > chunk_size and cur_words:
            out.append(" ".join(cur_words))
            cur_words, cur_len = [w], len(w)
        else:
            cur_words.append(w)
            cur_len += len(w) + 1
    if cur_words:
        out.append(" ".join(cur_words))
    return out


def _chunk_text(text: str, chunk_size: int = 1200) -> List[str]:
    """
    Particiona en fragmentos aproximadamente de chunk_size.
    1) Párrafos (bloques con línea en blanco).
    2) Si queda un solo bloque largo, partir por líneas (PDF de Word).
    3) Corte por palabras en bloques que sigan excediendo chunk_size.
    """
    text = re.sub(r"\r\n", "\n", text)
    text = text.replace("\r", "\n").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    parts, buf, current = [], [], 0
    # Párrafos: 2+ newlines o bloques
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]

    # Un solo monobloque con mucho texto (sin double newline) → empaqueta por líneas
    if len(paras) == 1 and len(paras[0]) > chunk_size * 1.15 and paras[0].count("\n") > 2:
        line_chunks = _pack_lines_to_chunks(paras[0], chunk_size)
        for lc in line_chunks:
            for piece in _chunk_by_words_if_needed(lc, chunk_size):
                if piece:
                    parts.append(piece)
        return parts

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

    final: List[str] = []
    for block in parts:
        for piece in _chunk_by_words_if_needed(block, chunk_size):
            if piece:
                final.append(piece)
    return final


def _insert_fragment(
    cur,
    doc_id: str,
    page_no: int,
    text: str,
    source: str,
    seq: int,
    bbox: Optional[str] = None,
) -> None:
    """Inserta un fragmento; seq conserva el orden de lectura dentro del documento.

    El parámetro ``bbox`` (string JSON ``[x1,y1,x2,y2]``) describe la zona del
    fragmento en la página original — útil para rendering en visor PDF y para
    citas precisas en RAG. Si la migración 0015 aún no corrió (columna ``bbox``
    o ``char_count`` ausentes), caemos a un INSERT clásico sin perderlo.
    """
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
    
    char_count = len(text or "")
    try:
        cur.execute(
            """
            INSERT OR REPLACE INTO fragments
            (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end,
             text, text_es, source, entities, created_at, seq, bbox, char_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?);
            """,
            (
                fragment_id,
                doc_id,
                None,
                None,
                page_no,
                page_no,
                text,
                None,
                source,
                entities_json,
                seq,
                bbox,
                char_count,
            ),
        )
    except Exception:
        # Migración 0015 todavía no aplicada en una BD legacy: insertamos sin
        # las nuevas columnas para no perder fragments.
        cur.execute(
            """
            INSERT OR REPLACE INTO fragments
            (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end,
             text, text_es, source, entities, created_at, seq)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?);
            """,
            (
                fragment_id,
                doc_id,
                None,
                None,
                page_no,
                page_no,
                text,
                None,
                source,
                entities_json,
                seq,
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


def _table_to_searchable_text(df, schema_obj: dict) -> str:
    """Serializa una tabla a un fragmento textual indexable.

    Combina cabeceras y celdas en oraciones cortas con separadores naturales
    (' | ' entre celdas, salto de línea entre filas) para que BM25 y el embedding
    capturen el contenido sin la estructura CSV cruda.
    """
    try:
        n_rows = int(df.shape[0])
        n_cols = int(df.shape[1])
    except Exception:
        return ""
    if n_rows == 0 or n_cols == 0:
        return ""
    rows: List[str] = []
    header = " | ".join(str(c).strip() for c in df.columns)
    if header.strip(" |"):
        rows.append(f"Tabla (encabezado): {header}")
    for r_idx in range(n_rows):
        cells: List[str] = []
        for c_idx in range(n_cols):
            try:
                val = df.iat[r_idx, c_idx]
            except Exception:
                val = ""
            s = "" if val is None else str(val).strip()
            if s:
                cells.append(s)
        if cells:
            rows.append(" | ".join(cells))
    flavor = schema_obj.get("flavor") if isinstance(schema_obj, dict) else None
    prefix = f"[Tabla {flavor or ''} {n_rows}x{n_cols}]".strip()
    return prefix + "\n" + "\n".join(rows)


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


def _clear_doc_extraction_rows(cur, doc_id: str) -> None:
    """Evita duplicar fragmentos/tablas al re-ejecutar extract sobre el mismo doc_id."""
    cur.execute("SELECT table_id FROM tables WHERE doc_id=?", (doc_id,))
    for (tid,) in cur.fetchall():
        cur.execute("DELETE FROM table_cells WHERE table_id=?", (tid,))
    cur.execute("DELETE FROM tables WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM fragments WHERE doc_id=?", (doc_id,))


def extract_document(
    conn,
    doc_id: str,
    pdf_path: str,
    ocr_missing_text: bool = True,
    extract_tables: Optional[str] = "auto",
    chunk_size: int = 1200,
    lang: Optional[str] = None,
    use_layout_dict: Optional[bool] = None,
    strip_repeating_headers: Optional[bool] = None,
    chunk_overlap: Optional[int] = None,
) -> dict:
    """
    Procesa un PDF de forma fiel al original:
      - Orden de lectura por bloques (layout) o sort; OCR sólo si la página
        trae menos de ``threshold`` caracteres.
      - El idioma de Tesseract se detecta automáticamente sobre las primeras
        páginas con texto nativo (``lang=None`` → autodetección). Pasar un
        valor explícito sigue funcionando.
      - Limpieza de líneas repetidas tipo cabecera/pié (muchas páginas).
      - Chunks con solapamiento opcional.
      - Bbox por fragmento (PDF coords) almacenado en ``fragments.bbox``.
      - Tablas Camelot lattice + stream con deduplicación por firma.
    Retorna contadores y metadatos.
    """
    use_l = (
        use_layout_dict
        if use_layout_dict is not None
        else _settings.EXTRACT_USE_LAYOUT_DICT
    )
    strip_r = (
        strip_repeating_headers
        if strip_repeating_headers is not None
        else _settings.EXTRACT_STRIP_REPEATING_PAGE_LINES
    )
    ov = (
        chunk_overlap
        if chunk_overlap is not None
        else int(getattr(_settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0)
    )
    if ov < 0:
        ov = 0

    cur = conn.cursor()
    _clear_doc_extraction_rows(cur, doc_id)

    doc = fitz.open(pdf_path)

    # Detectar lang OCR a partir del texto nativo accesible (3 primeras pgs).
    # Si el caller pasó ``lang`` explícito, lo respetamos sin filtrar por packs
    # disponibles (asume que sabe lo que hace).
    if lang is None:
        ocr_lang = _detect_doc_lang_for_ocr(doc)
    else:
        ocr_lang = lang

    # Flag operativo: extracción a nivel de bloque con bbox por fragmento real.
    # Activado por default (mejora fidelidad). Se puede desactivar vía settings
    # o pasando ``use_layout_dict=False`` para volver al modo "página completa".
    block_mode = bool(getattr(_settings, "EXTRACT_BLOCK_LEVEL", True))
    use_token_chunker = bool(getattr(_settings, "EXTRACT_TOKEN_CHUNKER", True))
    target_tokens = int(getattr(_settings, "EXTRACT_TARGET_TOKENS", 110) or 110)
    overlap_tokens = int(getattr(_settings, "EXTRACT_OVERLAP_TOKENS", 16) or 16)

    fragments_written = 0
    frag_seq = 0

    # Pre-cargamos tokenizer (puede ser None si HF no está disponible).
    tokenizer = get_tokenizer() if (use_token_chunker and block_mode) else None
    page_sources_for_audit: list[str] = []

    for i in range(doc.page_count):
        page_no = i + 1
        page = doc.load_page(i)
        native = _read_page_text_native(page, use_layout=use_l)
        use_ocr = ocr_missing_text and _page_needs_ocr(native)
        page_source = "native"

        if block_mode and not use_ocr:
            # ─── Camino 1: PDF nativo, fragmentar por bloques con bbox real ───
            pblocks = page_blocks(page)
            if not pblocks.blocks:
                page_sources_for_audit.append("native")
                continue
            groups = group_blocks_into_chunks(pblocks.blocks, target_chars=chunk_size)
            for grp in groups:
                grp_text = "\n\n".join(b.text for b in grp).strip()
                if not grp_text:
                    continue
                # Decisión:
                # 1) Si el grupo cabe en target_tokens → un único fragment con
                #    bbox = unión de bboxes de bloques.
                # 2) Si excede target_tokens → subdividimos por LÍNEAS, donde
                #    cada sub-chunk tiene bbox = unión de bboxes de las líneas
                #    que lo componen (bbox real fino, no el bbox del bloque).
                fits_window = (
                    tokenizer is None
                    or count_tokens(grp_text, tokenizer) <= target_tokens
                )
                if fits_window:
                    bbox = json.dumps(list(union_bbox(grp)))
                    try:
                        _insert_fragment(
                            cur, doc_id, page_no, grp_text, "native", frag_seq, bbox=bbox
                        )
                        frag_seq += 1
                        fragments_written += 1
                    except Exception as e:
                        print(f"[ERROR] Failed to insert fragment: {e}")
                    continue
                lines = collect_lines(grp)
                # Caracteres por chunk: dejamos un margen útil basado en el
                # target en tokens (≈ 4 chars/token medio para latín).
                target_chars_for_lines = max(target_tokens * 4, 240)
                line_groups = subdivide_lines_by_chars(lines, target_chars_for_lines)
                for lg in line_groups:
                    sub_text = "\n".join(l.text for l in lg).strip()
                    if not sub_text:
                        continue
                    # Si después de cortar por líneas un sub-chunk SIGUE
                    # excediendo target_tokens (líneas muy largas tipo
                    # one-liner gigante), aplicamos el chunker HF como
                    # último recurso para garantizar que el embed no se
                    # trunca; en ese caso conservamos el bbox del grupo de
                    # líneas (mejor aproximación disponible).
                    if tokenizer is not None and count_tokens(sub_text, tokenizer) > target_tokens:
                        sub_chunks = chunk_by_tokens(
                            sub_text,
                            target_tokens=target_tokens,
                            overlap_tokens=overlap_tokens,
                            tokenizer=tokenizer,
                        )
                    else:
                        sub_chunks = [sub_text]
                    bbox_lines = json.dumps(list(union_line_bbox(lg)))
                    for ch in sub_chunks:
                        c = (ch or "").strip()
                        if not c or len(c) < 2:
                            continue
                        try:
                            _insert_fragment(
                                cur, doc_id, page_no, c, "native", frag_seq, bbox=bbox_lines
                            )
                            frag_seq += 1
                            fragments_written += 1
                        except Exception as e:
                            print(f"[ERROR] Failed to insert fragment: {e}")
            page_sources_for_audit.append("native")
            continue

        if use_ocr:
            # ─── Camino 2: OCR regional por columnas (si OpenCV disponible) ──
            try:
                ocr_text, regions = ocr_page_by_regions(page, lang=ocr_lang)
                page_source = "ocr"
            except Exception:
                ocr_text = _ocr_page_image(page, lang=ocr_lang)
                regions = []
                page_source = "ocr"

            if regions and len(regions) > 1:
                # Tenemos múltiples columnas → cada región es un fragmento con
                # su bbox real. Aún así puede que un región muy largo necesite
                # chunk-by-tokens.
                for r in regions:
                    region_text = normalize_extracted_text(r.text)
                    if not region_text:
                        continue
                    bbox = json.dumps([r.x0, r.y0, r.x1, r.y1])
                    if tokenizer is not None and count_tokens(region_text, tokenizer) > target_tokens:
                        sub_chunks = chunk_by_tokens(
                            region_text,
                            target_tokens=target_tokens,
                            overlap_tokens=overlap_tokens,
                            tokenizer=tokenizer,
                        )
                    else:
                        sub_chunks = _chunk_text(region_text, chunk_size=chunk_size)
                    for ch in sub_chunks:
                        c = (ch or "").strip()
                        if not c or len(c) < 2:
                            continue
                        try:
                            _insert_fragment(
                                cur, doc_id, page_no, c, "ocr", frag_seq, bbox=bbox
                            )
                            frag_seq += 1
                            fragments_written += 1
                        except Exception as e:
                            print(f"[ERROR] Failed to insert OCR region fragment: {e}")
                page_sources_for_audit.append("ocr-regions")
                continue

            # OCR full-page (sin multi-col detectado o fallback)
            text_norm = normalize_extracted_text(ocr_text or "")
            if not text_norm:
                page_sources_for_audit.append("ocr-empty")
                continue
            bbox_json = _page_bbox(page)
            if tokenizer is not None and count_tokens(text_norm, tokenizer) > target_tokens:
                sub_chunks = chunk_by_tokens(
                    text_norm,
                    target_tokens=target_tokens,
                    overlap_tokens=overlap_tokens,
                    tokenizer=tokenizer,
                )
            else:
                sub_chunks = _chunk_text(text_norm, chunk_size=chunk_size)
                if ov:
                    sub_chunks = apply_chunk_overlap(sub_chunks, ov)
            for ch in sub_chunks:
                c = (ch or "").strip()
                if not c or len(c) < 2:
                    continue
                try:
                    _insert_fragment(cur, doc_id, page_no, c, "ocr", frag_seq, bbox=bbox_json)
                    frag_seq += 1
                    fragments_written += 1
                except Exception as e:
                    print(f"[ERROR] Failed to insert OCR fragment: {e}")
            page_sources_for_audit.append("ocr")
            continue

        # ─── Camino 3 (fallback): modo página completa (block_mode=False) ─────
        if not (native or "").strip():
            page_sources_for_audit.append("native-empty")
            continue
        bbox_json = _page_bbox(page)
        if tokenizer is not None and count_tokens(native, tokenizer) > target_tokens:
            sub_chunks = chunk_by_tokens(
                native,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
                tokenizer=tokenizer,
            )
        else:
            sub_chunks = _chunk_text(native, chunk_size=chunk_size)
            if ov:
                sub_chunks = apply_chunk_overlap(sub_chunks, ov)
        for ch in sub_chunks:
            c = (ch or "").strip()
            if not c or len(c) < 2:
                continue
            try:
                _insert_fragment(cur, doc_id, page_no, c, "native", frag_seq, bbox=bbox_json)
                frag_seq += 1
                fragments_written += 1
            except Exception as e:
                print(f"[ERROR] Failed to insert fragment: {e}")
        page_sources_for_audit.append("native-page")

    # --- Tablas (Camelot) con deduplicación cross-flavor ---
    tables_written = 0
    if _CAMELOT_OK and (extract_tables is None or extract_tables.lower() != "none"):
        mode = (extract_tables or "auto").lower()
        if mode == "lattice":
            flavors: List[str] = ["lattice"]
        elif mode == "stream":
            flavors = ["stream"]
        elif mode in ("lattice+stream", "stream+lattice", "auto"):
            flavors = ["lattice", "stream"]
        else:
            flavors = ["lattice", "stream"]

        seen_signatures: set[str] = set()
        for flavor in flavors:
            try:
                tables = camelot.read_pdf(pdf_path, pages="all", flavor=flavor)
            except Exception:
                continue
            for t in tables:
                df = t.df
                if int(df.shape[0]) == 0 or int(df.shape[1]) == 0:
                    continue
                sig = _table_signature(df)
                if sig in seen_signatures:
                    continue
                seen_signatures.add(sig)
                csv_text = df.to_csv(index=False, header=True)
                schema_obj = {
                    "n_rows": int(df.shape[0]),
                    "n_cols": int(df.shape[1]),
                    "flavor": flavor,
                    "signature": sig[:12],
                }
                page_no = int(getattr(t, "page", None) or 0) or 1
                bbox_json = None
                try:
                    if hasattr(t, "_bbox"):
                        bbox_json = json.dumps(list(t._bbox))
                except Exception:
                    bbox_json = None
                table_id = _insert_table(cur, doc_id, page_no, csv_text, bbox_json, schema_obj)
                _insert_table_cells(cur, table_id, df)
                tables_written += 1
                # Indexar contenido de la tabla como fragmento (BM25 + embeddings).
                table_text = _table_to_searchable_text(df, schema_obj)
                if table_text and len(table_text.strip()) >= 4:
                    _insert_fragment(
                        cur, doc_id, page_no, table_text, "table", frag_seq, bbox=bbox_json
                    )
                    frag_seq += 1
                    fragments_written += 1

    n_pages = doc.page_count
    try:
        doc.close()
    except Exception:
        pass
    return {
        "pages": n_pages,
        "fragments_written": fragments_written,
        "tables_written": tables_written,
        "extract": {
            "use_layout_dict": use_l,
            "strip_repeating_headers": strip_r,
            "chunk_overlap": ov,
            "ocr_lang": ocr_lang,
            "block_mode": block_mode,
            "token_chunker": tokenizer is not None,
            "target_tokens": target_tokens,
            "page_sources": page_sources_for_audit,
        },
    }


def extract_docx_to_db(
    conn,
    doc_id: str,
    docx_path: str,
    chunk_size: int = 1200,
    chunk_overlap: Optional[int] = None,
) -> dict:
    """Extrae un DOCX preservando estructura: párrafos, encabezados, listas y
    tablas. Persiste fragments con `bbox=None` (no aplica) y tablas en la
    tabla ``tables`` con su contenido como fragmento `source='table'`.
    """
    from milpa_ai_backend.core.logic.extract_docx import extract_docx
    cur = conn.cursor()
    _clear_doc_extraction_rows(cur, doc_id)

    extraction = extract_docx(docx_path)
    ov = (
        chunk_overlap
        if chunk_overlap is not None
        else int(getattr(_settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0)
    )
    if ov < 0:
        ov = 0

    fragments_written = 0
    tables_written = 0
    frag_seq = 0
    page_text_map = extraction.texts_per_page()

    # 1. Párrafos / encabezados / listas → fragments por página.
    for page in sorted(page_text_map.keys()):
        text = normalize_extracted_text(page_text_map[page])
        if not text:
            continue
        chunks = _chunk_text(text, chunk_size=chunk_size)
        if ov:
            chunks = apply_chunk_overlap(chunks, ov)
        for chunk in chunks:
            c = (chunk or "").strip()
            if not c or len(c) < 2:
                continue
            _insert_fragment(cur, doc_id, page, c, "native", frag_seq)
            frag_seq += 1
            fragments_written += 1

    # 2. Tablas explícitas del DOCX → tabla `tables` + fragment indexable.
    try:
        import pandas as pd
    except Exception:
        pd = None  # type: ignore

    for tb in extraction.get_tables():
        if not tb.table_rows:
            continue
        rows = tb.table_rows
        n_rows = len(rows)
        n_cols = max((len(r) for r in rows), default=0)
        if n_rows == 0 or n_cols == 0:
            continue
        # csv crudo
        csv_lines = []
        for r in rows:
            csv_lines.append(",".join(f'"{c.replace(chr(34), "")}"' for c in r))
        csv_text = "\n".join(csv_lines)
        schema_obj = {"n_rows": n_rows, "n_cols": n_cols, "flavor": "docx"}
        table_id = _insert_table(cur, doc_id, tb.page, csv_text, None, schema_obj)
        # Celdas (sin bbox, no aplica en DOCX).
        for r_idx, row in enumerate(rows):
            for c_idx, cell in enumerate(row):
                cur.execute(
                    """
                    INSERT OR REPLACE INTO table_cells
                    (table_id, row, col, text, bbox)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (table_id, r_idx, c_idx, cell, None),
                )
        tables_written += 1
        # Fragment indexable
        if pd is not None:
            df = pd.DataFrame(rows[1:] if n_rows > 1 else rows, columns=rows[0] if n_rows > 1 else [str(i) for i in range(n_cols)])
            table_text = _table_to_searchable_text(df, schema_obj)
        else:
            table_text = "\n".join(" | ".join(r) for r in rows)
        if table_text and len(table_text.strip()) >= 4:
            _insert_fragment(cur, doc_id, tb.page, table_text, "table", frag_seq)
            frag_seq += 1
            fragments_written += 1

    return {
        "pages": extraction.n_pages,
        "fragments_written": fragments_written,
        "tables_written": tables_written,
        "extract": {
            "format": "docx",
            "blocks": len(extraction.blocks),
            "chunk_overlap": ov,
        },
    }


def extract_text_to_db(
    conn,
    doc_id: str,
    text_path: str,
    chunk_size: int = 1200,
    chunk_overlap: Optional[int] = None,
) -> dict:
    """Ingresa un TXT/MD usando paginación lógica (form feed, h1 markdown o
    cada ~500 palabras), preservando encabezados y listas como fragments
    discretos."""
    from milpa_ai_backend.core.logic.extract_text import extract_text
    cur = conn.cursor()
    _clear_doc_extraction_rows(cur, doc_id)

    extraction = extract_text(text_path)
    ov = (
        chunk_overlap
        if chunk_overlap is not None
        else int(getattr(_settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0)
    )
    if ov < 0:
        ov = 0

    fragments_written = 0
    frag_seq = 0
    page_text_map = extraction.texts_per_page()
    for page in sorted(page_text_map.keys()):
        text = normalize_extracted_text(page_text_map[page])
        if not text:
            continue
        chunks = _chunk_text(text, chunk_size=chunk_size)
        if ov:
            chunks = apply_chunk_overlap(chunks, ov)
        for chunk in chunks:
            c = (chunk or "").strip()
            if not c or len(c) < 2:
                continue
            _insert_fragment(cur, doc_id, page, c, "native", frag_seq)
            frag_seq += 1
            fragments_written += 1

    return {
        "pages": extraction.n_pages,
        "fragments_written": fragments_written,
        "tables_written": 0,
        "extract": {
            "format": "text",
            "blocks": len(extraction.blocks),
            "chunk_overlap": ov,
        },
    }
