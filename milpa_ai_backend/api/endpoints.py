# milpa_ai_backend/api/endpoints.py
# Endpoints públicos del backend IA:
# - /api/documents/upload: subir archivo, escanear con AV (SCAN+INSTREAM), registrar metadatos.
# - /api/documents/{doc_id}/extract: extraer texto (nativo/OCR), tablas y fragmentos.

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Path, Query
from typing import Optional

from milpa_ai_backend.core.logic.ingestion import persist_original
from milpa_ai_backend.core.logic.db import get_conn
from milpa_ai_backend.core.security.av import scan_file_strict, AntivirusError
from milpa_ai_backend.core.config import settings
from pydantic import BaseModel
from typing import List

# Lógica de extracción (SPRINT 3–5)
from milpa_ai_backend.core.logic.extract import extract_document
from milpa_ai_backend.core.logic.pdf_metadata import (
    suggest_from_pdf_path,
    suggest_lang_from_text_snippet,
)
from pathlib import Path as PathLib

router = APIRouter()

# Tipos MIME permitidos (PDF, DOCX, TXT)
ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

# Catálogo de clasificación documental
ALLOWED_CLASSIFICATION = {"Publico", "Interno", "Restringido"}

# Catálogo de licencias válidas
ALLOWED_LICENSES = {"institutional", "public_domain", "permitted", "normative"}


def _optional_form_str(v: str | None) -> str | None:
    """Trata cadenas vacías o solo espacios como ausencia (útil con FormData)."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _merge_ingest_metadata(
    file_filename: str | None,
    title: str | None,
    author: str | None,
    year: int | None,
    stored_path: str,
) -> tuple[str, str | None, int | None]:
    """
    Título / autor / año: prioriza el formulario; si falta, metadatos PDF o nombre de archivo.
    """
    ext = (file_filename or "").rsplit(".", 1)[-1].lower() if file_filename else ""
    sug: dict = {}
    if ext == "pdf" and stored_path:
        try:
            sug = suggest_from_pdf_path(stored_path) or {}
        except Exception:
            sug = {}
    name_stem = PathLib(file_filename or (stored_path or "doc")).stem

    t = (title or "").strip() if title else ""
    if not t:
        t = (sug.get("title") or "").strip() or name_stem or "documento"
    a: str | None
    if author and str(author).strip():
        a = str(author).strip()
    else:
        a = (sug.get("author") or None)
    y: int | None
    if year is not None:
        y = int(year)
    else:
        y0 = sug.get("year")
        y = int(y0) if y0 is not None else None
    return (t, a, y)


def _update_lang_from_first_fragment(conn, doc_id: str) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT text FROM fragments WHERE doc_id=? ORDER BY page_start ASC, COALESCE(seq, 0) ASC LIMIT 1",
            (doc_id,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return
        cur.execute("SELECT COALESCE(lang_original, '') FROM docs WHERE doc_id=?", (doc_id,))
        r2 = cur.fetchone()
        if r2 and (r2[0] or "").strip():
            return
        lang = suggest_lang_from_text_snippet(str(row[0])[:4000])
        if lang:
            cur.execute("UPDATE docs SET lang_original=? WHERE doc_id=?", (lang, doc_id))
    except Exception:
        pass


@router.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(..., description="Documento PDF/DOCX/TXT"),
    license: str = Form("institutional", description="Tipo de licencia"),
    classification: str = Form("Interno", description="Clasificación: Publico/Interno/Restringido"),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    license_url: Optional[str] = Form(None),
):
    """
    Sube un documento y registra metadatos mínimos.

    Flujo:
      1) Validar MIME, tamaño (aprox) y parámetros (licencia/clasificación).
      2) Persistir original en data/documents con nombre canonizado.
      3) Escanear con ClamAV *estricto* (SCAN + INSTREAM). Si detecta malware → 400.
      4) Calcular SHA-256 (lo devuelve persistencia) → doc_id.
      5) Insertar/actualizar metadatos en tabla docs y licenses (incluye stored_path).
    """
    # Validar MIME
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Tipo no permitido: {file.content_type}")

    # Validar clasificación
    if classification not in ALLOWED_CLASSIFICATION:
        raise HTTPException(status_code=400, detail=f"classification debe estar en {ALLOWED_CLASSIFICATION}")

    # Validar licencia
    if license not in ALLOWED_LICENSES:
        raise HTTPException(status_code=400, detail=f"license debe estar en {ALLOWED_LICENSES}")

    # Validación simple de tamaño (si el cliente envía Content-Length)
    if getattr(file, "size", None) and file.size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Archivo excede el límite de {settings.MAX_UPLOAD_MB} MB")

    # Guardar en disco → ruta y digest (doc_id)
    stored_path, digest = persist_original(file.file, file.filename)

    # AV estricto (SCAN + INSTREAM)
    try:
        scan_file_strict(stored_path)
    except AntivirusError as e:
        raise HTTPException(status_code=400, detail=f"Antivirus: {str(e)}")

    ut, ua, uy = _merge_ingest_metadata(
        file.filename,
        _optional_form_str(title),
        _optional_form_str(author),
        year,
        str(stored_path),
    )
    # Registrar metadatos en SQLite (incluye stored_path)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO docs
            (doc_id, title, author, year, source, hash, license, lang_original, classification, created_at, stored_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?);
            """,
            (
                digest,
                ut,
                ua,
                uy,
                file.filename,  # nombre fuente original
                digest,
                license,
                None,           # lang_original: extract / fragmentos o heurística
                classification,
                stored_path,    # <--- importante: guardamos stored_path real
            ),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO licenses
            (doc_id, license, url, checked_by, checked_at)
            VALUES (?, ?, ?, ?, datetime('now'));
            """,
            (digest, license, license_url, "uploader"),
        )
        conn.commit()

    return {
        "doc_id": digest,
        "stored_path": stored_path,
        "license": license,
        "classification": classification,
        "title": ut,
        "author": ua,
        "year": uy,
    }


# ---------- EXTRACCIÓN (SPRINT 3–5) ----------

class ExtractOptions(BaseModel):
    ocr_missing_text: bool = True
    extract_tables: Optional[str] = "auto"   # None | "auto" | "lattice" | "stream" | "lattice+stream"
    chunk_size: int = 1200                   # tamaño de fragmento textual
    lang: str = "spa+eng"                    # idiomas Tesseract (si usas OCR)
    use_layout_dict: Optional[bool] = None   # None → env / default
    strip_repeating_headers: Optional[bool] = None
    chunk_overlap: Optional[int] = None     # caracteres de solape entre fragmentos (0 = off)


@router.post("/api/documents/{doc_id}/extract")
async def extract_endpoint(
    doc_id: str = Path(..., description="Hash SHA-256 del documento (doc_id)"),
    opts: ExtractOptions = None,
):
    """
    Extrae contenido del PDF:
      - Texto nativo por página. Si hay muy poco texto y ocr_missing_text=True, aplica OCR (Tesseract).
      - Tablas con Camelot (lattice/stream/auto).
      - Realiza chunking básico y persiste en tablas: fragments, tables, table_cells.
    Devuelve contadores.
    """
    # Cargar metadatos y stored_path de DB
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stored_path, source FROM docs WHERE doc_id=?;", (doc_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        stored_path, source_name = row
        if not stored_path:
            raise HTTPException(status_code=500, detail="stored_path no disponible en DB (subida previa sin stored_path)")

        # Ejecutar extracción
        try:
            result = extract_document(
                conn=conn,
                doc_id=doc_id,
                pdf_path=stored_path,
                ocr_missing_text=(opts.ocr_missing_text if opts else True),
                extract_tables=(opts.extract_tables if opts else "auto"),
                chunk_size=(opts.chunk_size if opts else 1200),
                # opts.lang opcional: si el cliente no lo manda, autodetección.
                lang=(opts.lang if opts else None),
                use_layout_dict=opts.use_layout_dict if opts else None,
                strip_repeating_headers=opts.strip_repeating_headers if opts else None,
                chunk_overlap=opts.chunk_overlap if opts else None,
            )
            print(f"[DEBUG] Extraction complete, fragments={result.get('fragments_written',0)}")
            print(f"[DEBUG] Committing transaction...")
            conn.commit()
            print(f"[DEBUG] Commit successful")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Archivo físico no encontrado en stored_path")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error en extracción: {e}")

    return {"doc_id": doc_id, **result}


# ---------- INGEST UNIFICADO (upload + extract + index) ----------

@router.post("/api/documents/ingest")
async def ingest_document(
    file: UploadFile = File(..., description="Documento PDF/DOCX/TXT"),
    license: str = Form("public_domain"),
    classification: str = Form("Publico"),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    license_url: Optional[str] = Form(None),
    chunk_size: int = Form(1200),
):
    """
    Pipeline unificado: sube, extrae texto/tablas e indexa en BM25+vectorial.
    Un solo endpoint para que un documento quede disponible para consultas RAG.
    """
    import logging
    _log = logging.getLogger("ingest")

    # 1) Validaciones
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Tipo no permitido: {file.content_type}")
    if classification not in ALLOWED_CLASSIFICATION:
        raise HTTPException(status_code=400, detail=f"classification debe estar en {ALLOWED_CLASSIFICATION}")
    if license not in ALLOWED_LICENSES:
        raise HTTPException(status_code=400, detail=f"license debe estar en {ALLOWED_LICENSES}")
    if getattr(file, "size", None) and file.size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Archivo excede {settings.MAX_UPLOAD_MB} MB")

    # 2) Guardar archivo original en disco
    stored_path, digest = persist_original(file.file, file.filename)
    _log.info(f"Archivo guardado: {stored_path} (SHA-256: {digest[:12]}...)")

    # 3) Escanear con AV
    try:
        scan_file_strict(stored_path)
    except AntivirusError as e:
        raise HTTPException(status_code=400, detail=f"Antivirus: {str(e)}")

    # 4) Metadatos (formulario; si faltan campos en PDF, sugerencia desde /Info + fecha)
    meta_title, meta_author, meta_year = _merge_ingest_metadata(
        file.filename,
        _optional_form_str(title),
        _optional_form_str(author),
        year,
        stored_path,
    )
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO docs
            (doc_id, title, author, year, source, hash, license, lang_original,
             classification, created_at, stored_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
            (digest, meta_title, meta_author, meta_year, file.filename,
             digest, license, None, classification, stored_path),
        )
        cur.execute(
            """INSERT OR REPLACE INTO licenses
            (doc_id, license, url, checked_by, checked_at)
            VALUES (?, ?, ?, 'uploader', datetime('now'))""",
            (digest, license, license_url),
        )
        conn.commit()

    # 5) Extraer texto y tablas (PDF nativo+OCR; TXT/DOCX directo)
    fragments_written = 0
    tables_written = 0
    pages = 0

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""

    if ext == "pdf":
        with get_conn() as conn:
            try:
                result = extract_document(
                    conn=conn, doc_id=digest, pdf_path=stored_path,
                    ocr_missing_text=True, extract_tables="auto",
                    chunk_size=chunk_size,
                    # lang=None → autodetección por idioma del documento
                    lang=None,
                    use_layout_dict=None,
                    strip_repeating_headers=None,
                    chunk_overlap=int(getattr(settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0),
                )
                _update_lang_from_first_fragment(conn, digest)
                conn.commit()
                fragments_written = result.get("fragments_written", 0)
                tables_written = result.get("tables_written", 0)
                pages = result.get("pages", 0)
            except Exception as e:
                _log.warning(f"Extraccion PDF parcial: {e}")
    elif ext in ("txt", "text", "md"):
        from milpa_ai_backend.core.logic.extract import extract_text_to_db
        with get_conn() as conn:
            try:
                result = extract_text_to_db(
                    conn=conn,
                    doc_id=digest,
                    text_path=stored_path,
                    chunk_size=chunk_size,
                    chunk_overlap=int(getattr(settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0),
                )
                _update_lang_from_first_fragment(conn, digest)
                conn.commit()
                fragments_written = result.get("fragments_written", 0)
                pages = result.get("pages", 1)
            except Exception as e:
                _log.warning(f"Extraccion TXT/MD parcial: {e}")
    elif ext == "docx":
        from milpa_ai_backend.core.logic.extract import extract_docx_to_db
        with get_conn() as conn:
            try:
                result = extract_docx_to_db(
                    conn=conn,
                    doc_id=digest,
                    docx_path=stored_path,
                    chunk_size=chunk_size,
                    chunk_overlap=int(getattr(settings, "EXTRACT_CHUNK_OVERLAP_CHARS", 0) or 0),
                )
                _update_lang_from_first_fragment(conn, digest)
                conn.commit()
                fragments_written = result.get("fragments_written", 0)
                tables_written = result.get("tables_written", 0)
                pages = result.get("pages", 1)
            except ImportError:
                _log.warning("python-docx no instalado; DOCX guardado sin extraer texto")
            except Exception as e:
                _log.warning(f"Extraccion DOCX parcial: {e}")

    # 6) Indexar fragmentos en BM25 + ChromaDB
    indexed = 0
    if fragments_written > 0:
        try:
            from milpa_ai_backend.api.rag import index_doc_fragments
            idx_result = index_doc_fragments(digest)
            indexed = idx_result.get("indexed", 0)
        except Exception as e:
            _log.warning(f"Indexacion parcial: {e}")

    return {
        "status": "ok",
        "doc_id": digest,
        "title": meta_title,
        "stored_path": stored_path,
        "pages": pages,
        "fragments": fragments_written,
        "tables": tables_written,
        "indexed": indexed,
    }


@router.get("/api/documents/{doc_id}/diagnose")
def diagnose_document(
    doc_id: str = Path(..., description="Hash SHA-256 del documento"),
    sample_chars: int = Query(default=200, ge=0, le=2000),
):
    """Diagnóstico de extracción para un documento ya ingestado.

    Devuelve metadatos del documento, conteos por página/fuente, totales de
    tablas y muestras cortas del primer fragmento de cada página. Útil para
    verificar el efecto de cambios en el pipeline sin abrir la BD a mano.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, title, author, year, source, classification, "
            "license, lang_original, stored_path, created_at "
            "FROM docs WHERE doc_id=?",
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="doc_id no encontrado")
        cols = [d[0] for d in cur.description]
        meta = dict(zip(cols, row))

        cur.execute(
            "SELECT page_start, source, COUNT(*) AS n, SUM(LENGTH(text)) AS chars "
            "FROM fragments WHERE doc_id=? GROUP BY page_start, source "
            "ORDER BY page_start, source",
            (doc_id,),
        )
        per_page = [
            {"page": r[0], "source": r[1], "fragments": r[2], "chars": r[3] or 0}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT COALESCE(source, 'unknown') AS s, COUNT(*) AS n, "
            "COALESCE(SUM(LENGTH(text)), 0) AS chars "
            "FROM fragments WHERE doc_id=? GROUP BY s",
            (doc_id,),
        )
        by_source = [
            {"source": r[0], "fragments": r[1], "chars": r[2]} for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT COUNT(*) AS n_tables, COALESCE(SUM(LENGTH(csv)), 0) AS csv_bytes "
            "FROM tables WHERE doc_id=?",
            (doc_id,),
        )
        t_row = cur.fetchone()
        tables = {"n_tables": t_row[0], "csv_bytes": t_row[1]}

        cur.execute(
            "SELECT page_start, source, fragment_id, text "
            "FROM fragments WHERE doc_id=? ORDER BY page_start, COALESCE(seq, 0)",
            (doc_id,),
        )
        seen_pages: set = set()
        samples: list = []
        for page_start, source, fragment_id, text in cur.fetchall():
            if page_start in seen_pages:
                continue
            seen_pages.add(page_start)
            snippet = (text or "")[:sample_chars]
            samples.append(
                {
                    "page": page_start,
                    "source": source,
                    "fragment_id": fragment_id,
                    "sample": snippet,
                }
            )

    return {
        "doc": meta,
        "totals": {
            "fragments": sum(p["fragments"] for p in per_page),
            "chars": sum(p["chars"] for p in per_page),
            "tables": tables,
            "by_source": by_source,
        },
        "per_page": per_page,
        "samples": samples,
    }


@router.delete("/api/documents/{doc_id}")
def delete_document(
    doc_id: str = Path(..., description="Hash SHA-256 del documento a borrar"),
):
    """Elimina un documento de SQLite, BM25 y ChromaDB.

    Esta operación es idempotente: si el documento ya no existe en SQLite, se
    siguen intentando las purgas de BM25/ChromaDB para limpiar fragments
    huérfanos. Devuelve un resumen con conteos por almacén.
    """
    from milpa_ai_backend.api.rag import get_retriever
    summary = {"doc_id": doc_id, "sqlite": {}, "bm25": 0, "chroma": 0}

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT table_id FROM tables WHERE doc_id=?", (doc_id,))
        table_ids = [r[0] for r in cur.fetchall()]
        for tid in table_ids:
            cur.execute("DELETE FROM table_cells WHERE table_id=?", (tid,))
        cur.execute("DELETE FROM tables WHERE doc_id=?", (doc_id,))
        deleted_tables = cur.rowcount
        cur.execute("DELETE FROM fragments WHERE doc_id=?", (doc_id,))
        deleted_frag = cur.rowcount
        cur.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))
        deleted_docs = cur.rowcount
        try:
            cur.execute("DELETE FROM licenses WHERE doc_id=?", (doc_id,))
        except Exception:
            pass
        conn.commit()
        summary["sqlite"] = {
            "docs": deleted_docs,
            "fragments": deleted_frag,
            "tables": deleted_tables,
        }

    try:
        retriever = get_retriever()
        try:
            summary["bm25"] = int(retriever.bm25.delete_by_doc_id(doc_id) or 0)
        except Exception:
            summary["bm25"] = 0
        try:
            retriever.vs.col.delete(where={"doc_id": doc_id})
            summary["chroma"] = 1
        except Exception:
            summary["chroma"] = 0
    except Exception:
        pass

    return summary


@router.post("/api/admin/reconcile-indexes")
def reconcile_indexes():
    """Reconcilia BM25 y ChromaDB con SQLite.

    Encuentra todos los ``doc_id`` presentes en BM25/Chroma que ya no existen
    en ``docs`` y los purga. Útil tras runs de pruebas o limpiezas manuales en
    SQLite que dejan fragments huérfanos en los índices y degradan el ranking.
    """
    from milpa_ai_backend.api.rag import get_retriever
    summary = {"valid_docs": 0, "bm25_purged": [], "chroma_purged": []}

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT doc_id FROM docs")
        valid = {r[0] for r in cur.fetchall() if r[0]}
    summary["valid_docs"] = len(valid)

    retriever = get_retriever()

    chroma_doc_ids: set[str] = set()
    try:
        peek = retriever.vs.col.get(include=["metadatas"], limit=100000)
        for md in peek.get("metadatas") or []:
            d = (md or {}).get("doc_id")
            if d:
                chroma_doc_ids.add(d)
    except Exception:
        pass

    for did in chroma_doc_ids - valid:
        try:
            retriever.vs.col.delete(where={"doc_id": did})
            summary["chroma_purged"].append(did)
        except Exception:
            pass

    bm25_doc_ids: set[str] = set()
    try:
        # Whoosh y Tantivy: enumeramos hits con un query muy laxo y juntamos
        # los doc_id que aparezcan. Es best-effort: si no podemos enumerarlos
        # caemos a chroma como fuente de verdad.
        seeds = ["a", "e", "i", "o", "u", "milpa", "table"]
        for q in seeds:
            for h in retriever.bm25.search(q, topk=1000):
                d = (h.get("metadata") or {}).get("doc_id")
                if d:
                    bm25_doc_ids.add(d)
    except Exception:
        pass
    bm25_doc_ids |= chroma_doc_ids

    for did in bm25_doc_ids - valid:
        try:
            retriever.bm25.delete_by_doc_id(did)
            summary["bm25_purged"].append(did)
        except Exception:
            pass

    return summary


@router.get("/api/documents/{doc_id}/render")
def render_document_page(
    doc_id: str = Path(..., description="Hash SHA-256 del documento"),
    page: int = Query(..., ge=1, description="Número de página (1-based)"),
    fragment_id: Optional[str] = Query(default=None, description="Fragmento a resaltar"),
    scale: float = Query(default=2.0, ge=0.5, le=6.0),
    highlight_all: bool = Query(default=False, description="Pinta bbox de TODOS los fragments"),
):
    """Renderiza una página del PDF con overlays de bbox por fragmento.

    Devuelve un PNG con:
      - La página renderizada del PDF a ``scale`` (1.0 = 72 DPI).
      - Si se pasa ``fragment_id``: rectángulo amarillo semi-transparente sobre
        ese fragmento.
      - Si ``highlight_all=true``: rectángulos azules suaves sobre cada
        fragmento de la página, útil para auditar la fragmentación.

    Para DOCX/TXT (sin PDF físico) devuelve 415.
    """
    from io import BytesIO
    import json as _json
    import fitz  # type: ignore
    from PIL import Image, ImageDraw  # type: ignore
    from fastapi.responses import Response

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stored_path FROM docs WHERE doc_id=?", (doc_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="doc_id no encontrado")
        stored_path = row[0]
        if not stored_path or not stored_path.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="render solo disponible para PDFs")
        if not PathLib(stored_path).is_file():
            raise HTTPException(status_code=410, detail="archivo físico no encontrado")
        cur.execute(
            "SELECT fragment_id, page_start, bbox FROM fragments "
            "WHERE doc_id=? AND page_start=?",
            (doc_id, page),
        )
        rows = cur.fetchall()
        target_bbox = None
        all_bboxes: list[list[float]] = []
        for fid, _p, bbox_json in rows:
            if not bbox_json:
                continue
            try:
                bb = _json.loads(bbox_json)
            except Exception:
                continue
            if not isinstance(bb, list) or len(bb) < 4:
                continue
            if fragment_id and fid == fragment_id:
                target_bbox = bb
            all_bboxes.append(bb)

    try:
        pdf = fitz.open(stored_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PyMuPDF no pudo abrir: {e}")
    try:
        if page < 1 or page > pdf.page_count:
            raise HTTPException(
                status_code=400, detail=f"page fuera de rango (1..{pdf.page_count})"
            )
        pg = pdf.load_page(page - 1)
        mat = fitz.Matrix(scale, scale)
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
    finally:
        pdf.close()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def _scale_bbox(bb: list[float]) -> tuple[int, int, int, int]:
        return (
            int(bb[0] * scale),
            int(bb[1] * scale),
            int(bb[2] * scale),
            int(bb[3] * scale),
        )

    if highlight_all:
        for bb in all_bboxes:
            x0, y0, x1, y1 = _scale_bbox(bb)
            draw.rectangle([x0, y0, x1, y1], outline=(40, 90, 220, 255), width=2)
            draw.rectangle([x0, y0, x1, y1], fill=(40, 90, 220, 30))

    if target_bbox is not None:
        x0, y0, x1, y1 = _scale_bbox(target_bbox)
        draw.rectangle([x0, y0, x1, y1], outline=(255, 200, 0, 255), width=4)
        draw.rectangle([x0, y0, x1, y1], fill=(255, 230, 0, 70))

    composed = Image.alpha_composite(img, overlay).convert("RGB")
    buf = BytesIO()
    composed.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")


@router.get("/api/documents/{doc_id}/fragments/{fragment_id}/locate")
def locate_fragment(
    doc_id: str = Path(...),
    fragment_id: str = Path(...),
):
    """Devuelve la información necesaria para que el visor del frontend
    pinte el fragmento sobre la página correspondiente: ``page``, ``bbox``,
    ``page_dimensions`` (en puntos PDF) y URL del render.
    """
    import json as _json
    import fitz  # type: ignore

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT page_start, bbox, text, source FROM fragments "
            "WHERE doc_id=? AND fragment_id=?",
            (doc_id, fragment_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="fragment_id no encontrado")
        page, bbox_json, text, source = row
        cur.execute("SELECT stored_path FROM docs WHERE doc_id=?", (doc_id,))
        sp = cur.fetchone()
        stored_path = sp[0] if sp else None

    bbox = None
    if bbox_json:
        try:
            bbox = _json.loads(bbox_json)
        except Exception:
            bbox = None

    page_w = page_h = None
    if stored_path and stored_path.lower().endswith(".pdf") and PathLib(stored_path).is_file():
        try:
            pdf = fitz.open(stored_path)
            try:
                if 1 <= page <= pdf.page_count:
                    pg = pdf.load_page(page - 1)
                    page_w = float(pg.rect.width)
                    page_h = float(pg.rect.height)
            finally:
                pdf.close()
        except Exception:
            pass

    return {
        "fragment_id": fragment_id,
        "doc_id": doc_id,
        "page": page,
        "bbox": bbox,
        "source": source,
        "text_preview": (text or "")[:200],
        "page_dimensions": {"width": page_w, "height": page_h},
        "render_url": f"/api/documents/{doc_id}/render?page={page}&fragment_id={fragment_id}",
    }


# ---------------------- BIBLIOTECA ----------------------
@router.get("/library")
def list_library(
    q: str | None = Query(default=None, description="Búsqueda por nombre/autor/fuente"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    year: int | None = Query(default=None, description="Filtrar por año exacto"),
    author: str | None = Query(default=None, description="Filtrar por autor exacto"),
    word: bool = Query(default=False, description="Buscar por palabra exacta (tokens)"),
):
    """
    Lista documentos registrados en la base y los mapea a la forma esperada por la UI
    "Biblioteca": nombre, autor, año, tipo, país, idioma, extraido_de.

    Notas:
    - "tipo" se deriva de la extensión del archivo "source" (pdf, docx, txt, etc.).
    - "país" e "idioma" no están en el esquema mínimo; se devuelven como None.
    - "extraido_de" se mapea desde "source" (nombre del archivo original) o stored_path si aplica.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        # Semilla: insertar documentos de prueba si no existen
        try:
            # PDF demo
            pdf_path = PathLib("data/documents/demo_biblioteca.pdf")
            if pdf_path.exists():
                cur.execute("SELECT 1 FROM docs WHERE source=? LIMIT 1;", (pdf_path.name,))
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO docs (doc_id, title, author, year, source, hash, license, lang_original, classification, created_at, stored_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?);
                        """,
                        (
                            "demo-pdf-1",
                            "Documento de prueba Biblioteca (PDF)",
                            "Jane Doe",
                            2025,
                            pdf_path.name,
                            "demo-pdf-1",
                            "public_domain",
                            "es",
                            "Publico",
                            str(pdf_path.resolve()),
                        ),
                    )
            # TX demo
            tx_path = PathLib("data/documents/demo_biblioteca.tx")
            if tx_path.exists():
                cur.execute("SELECT 1 FROM docs WHERE source=? LIMIT 1;", (tx_path.name,))
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO docs (doc_id, title, author, year, source, hash, license, lang_original, classification, created_at, stored_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?);
                        """,
                        (
                            "demo-tx-1",
                            "Documento de prueba Biblioteca (TX)",
                            "Juan Pérez",
                            2024,
                            tx_path.name,
                            "demo-tx-1",
                            "public_domain",
                            "es",
                            "Publico",
                            str(tx_path.resolve()),
                        ),
                    )
            conn.commit()
        except Exception:
            # Si falla la semilla, no impedir la lectura normal
            pass
        # Construcción dinámica de filtros: q (LIKE o tokens AND), year, author
        clauses: list[str] = []
        params: list[object] = []
        if q:
            q_norm = q.strip().lower()  # normalizar a minúsculas para búsqueda case-insensitive confiable
            if word:
                # Tokens separados por espacios (AND)
                tokens = [t for t in q_norm.split() if t]
                for t in tokens:
                    like = f"%{t}%"
                    # Buscar en metadatos (docs) y contenido (fragments)
                    clauses.append(
                        "(LOWER(COALESCE(docs.title,'')) LIKE ? OR LOWER(COALESCE(docs.author,'')) LIKE ? OR LOWER(COALESCE(docs.source,'')) LIKE ? "
                        "OR EXISTS (SELECT 1 FROM fragments WHERE fragments.doc_id = docs.doc_id AND LOWER(COALESCE(fragments.text,'')) LIKE ?))"
                    )
                    params.extend([like, like, like, like])
            else:
                like = f"%{q_norm}%"
                # Buscar en metadatos (docs) y contenido (fragments)
                clauses.append(
                    "(LOWER(COALESCE(docs.title,'')) LIKE ? OR LOWER(COALESCE(docs.author,'')) LIKE ? OR LOWER(COALESCE(docs.source,'')) LIKE ? "
                    "OR EXISTS (SELECT 1 FROM fragments WHERE fragments.doc_id = docs.doc_id AND LOWER(COALESCE(fragments.text,'')) LIKE ?))"
                )
                params.extend([like, like, like, like])
        if year is not None:
            clauses.append("docs.year = ?")
            params.append(year)
        if author:
            clauses.append("docs.author = ?")
            params.append(author)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Total para paginar
        cur.execute(f"SELECT COUNT(1) FROM docs {where}", params)
        row_total = cur.fetchone()
        total = int(row_total[0]) if row_total else 0
        # Página
        params_page = list(params)
        params_page.extend([limit, offset])
        cur.execute(
            f"""
            SELECT docs.doc_id, docs.title, docs.author, docs.year, docs.source, docs.stored_path, docs.lang_original
            FROM docs
            {where}
            ORDER BY docs.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params_page,
        )
        rows = cur.fetchall()

    items = []
    for (doc_id, title, author, year, source, stored_path, lang_original) in rows:
        # Derivar tipo desde la extensión del source
        ext = None
        if isinstance(source, str) and "." in source:
            ext = source.rsplit(".", 1)[-1].lower()
        tipo = ext or "desconocido"

        items.append({
            "id": doc_id,
            "nombre": title or source or doc_id,
            "autor": author,
            "año": year,
            "tipo": tipo,
            "país": None,
            "idioma": lang_original,
            "extraido_de": source or stored_path,
        })

    return {"items": items, "total": total, "offset": offset, "limit": limit, "q": q, "year": year, "author": author, "word": word}


@router.get("/library/facets")
def library_facets():
    """Devuelve facetas básicas: autores (alfabético) y años disponibles."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT author FROM docs WHERE author IS NOT NULL AND author <> ''")
        authors = sorted([r[0] for r in cur.fetchall()])
        cur.execute("SELECT DISTINCT year FROM docs WHERE year IS NOT NULL ORDER BY year DESC")
        years = [r[0] for r in cur.fetchall()]
    return {"authors": authors, "years": years}


def _parse_csv_to_rows(csv_text: str) -> List[List[str]]:
    """Parsea CSV soportando delimitador coma o punto y coma y comillas escapadas."""
    import csv, io
    if not csv_text:
        return []
    sample = csv_text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[',', ';', '\t'])
    except Exception:
        class _Dialect(csv.Dialect):
            delimiter = ','
            quotechar = '"'
            doublequote = True
            skipinitialspace = True
            lineterminator = '\n'
            quoting = csv.QUOTE_MINIMAL
        dialect = _Dialect()
    rows: List[List[str]] = []
    reader = csv.reader(io.StringIO(csv_text), dialect)
    for r in reader:
        rows.append([c.strip() for c in r])
    return rows


@router.get("/library/{doc_id}")
def library_detail(doc_id: str):
    """
    Devuelve metadatos y tablas (si existen) para un documento de la biblioteca.
    Estructura:
    {
      doc_id, nombre, autor, año, tipo, país, idioma, extraido_de,
      classification, license,
      tables: [ { table_id, page, n_rows, n_cols, headers, rows } ]
    }
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doc_id, title, author, year, source, stored_path, classification, license, lang_original
            FROM docs WHERE doc_id=?
            """,
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        doc_id_v, title, author, year, source, stored_path, classification, license, lang_original = row

        # Derivar tipo desde la extensión del source
        ext = None
        if isinstance(source, str) and "." in source:
            ext = source.rsplit(".", 1)[-1].lower()
        tipo = ext or "desconocido"

        # Cargar tablas (máximo 5 para vista)
        cur.execute(
            """
            SELECT table_id, page, csv FROM tables WHERE doc_id=? ORDER BY page ASC LIMIT 5
            """,
            (doc_id,),
        )
        trows = cur.fetchall() or []
        tables = []
        for (table_id, page, csv_text) in trows:
            rows_list = _parse_csv_to_rows(csv_text or "")
            n_rows = len(rows_list)
            n_cols = max((len(r) for r in rows_list), default=0)
            headers = rows_list[0] if n_rows > 0 else []
            body_rows = rows_list[1:] if n_rows > 1 else []
            tables.append({
                "table_id": table_id,
                "page": page,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "headers": headers,
                "rows": body_rows,
            })

        # Cargar fragmentos de texto (máximo 20 para vista)
        cur.execute(
            """
            SELECT fragment_id, text, page_start FROM fragments WHERE doc_id=? ORDER BY page_start ASC, COALESCE(seq, 0) ASC, fragment_id ASC LIMIT 20
            """,
            (doc_id,),
        )
        frag_rows = cur.fetchall() or []
        fragments = []
        for (frag_id, text, page_start) in frag_rows:
            fragments.append({
                "fragment_id": frag_id,
                "text": text,
                "page": page_start,
            })

    return {
        "doc_id": doc_id_v,
        "nombre": title or source or doc_id_v,
        "autor": author,
        "año": year,
        "tipo": tipo,
        "país": None,
        "idioma": lang_original,
        "extraido_de": source or stored_path,
        "classification": classification,
        "license": license,
        "tables": tables,
        "fragments": fragments,
    }


# ────────────────────────────────────────────────────────────────
# SPRINT 20: Administración de Feature Flags
# ────────────────────────────────────────────────────────────────

class FeatureFlagResponse(BaseModel):
    flag_name: str
    enabled: bool
    config: dict
    description: Optional[str] = None


@router.get("/admin/feature-flags")
def list_feature_flags():
    """Lista todos los feature flags disponibles."""
    try:
        from milpa_ai_backend.core.config_flags.feature_flags import feature_flags
        feature_flags.reload()  # Asegurar datos frescos
        
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT flag_name, enabled, config_json, description
                FROM feature_flags
                ORDER BY flag_name
            """)
            
            import json
            flags = []
            for row in cur.fetchall():
                flag_name, enabled, config_json, description = row
                flags.append({
                    "flag_name": flag_name,
                    "enabled": bool(enabled),
                    "config": json.loads(config_json) if config_json else {},
                    "description": description
                })
            
            return {"flags": flags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing feature flags: {str(e)}")


@router.get("/admin/feature-flags/{flag_name}")
def get_feature_flag(flag_name: str):
    """Obtiene un feature flag específico."""
    try:
        from milpa_ai_backend.core.config_flags.feature_flags import feature_flags
        
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT flag_name, enabled, config_json, description
                FROM feature_flags
                WHERE flag_name = ?
            """, (flag_name,))
            
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
            
            import json
            flag_name_db, enabled, config_json, description = row
            return {
                "flag_name": flag_name_db,
                "enabled": bool(enabled),
                "config": json.loads(config_json) if config_json else {},
                "description": description
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting feature flag: {str(e)}")


@router.put("/admin/feature-flags/{flag_name}")
def update_feature_flag(
    flag_name: str,
    enabled: bool = Query(..., description="Enable or disable the flag"),
    config: Optional[dict] = None
):
    """Actualiza un feature flag (requiere autenticación en producción)."""
    try:
        from milpa_ai_backend.core.config_flags.feature_flags import feature_flags
        
        # Verificar que el flag existe
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT flag_name FROM feature_flags WHERE flag_name = ?", (flag_name,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
        
        # Actualizar usando el sistema de feature flags
        feature_flags.set_flag(flag_name, enabled, config)
        
        return {
            "message": f"Feature flag '{flag_name}' updated successfully",
            "flag_name": flag_name,
            "enabled": enabled,
            "config": config
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating feature flag: {str(e)}")
