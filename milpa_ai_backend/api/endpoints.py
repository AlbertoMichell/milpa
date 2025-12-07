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
                title,
                author,
                year,
                file.filename,  # nombre fuente original
                digest,
                license,
                None,           # lang_original se completa luego si procede
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
        "title": title,
        "author": author,
        "year": year,
    }


# ---------- EXTRACCIÓN (SPRINT 3–5) ----------

class ExtractOptions(BaseModel):
    ocr_missing_text: bool = True
    extract_tables: Optional[str] = "auto"   # None | "auto" | "lattice" | "stream" | "lattice+stream"
    chunk_size: int = 1200                   # tamaño de fragmento textual
    lang: str = "spa+eng"                    # idiomas Tesseract (si usas OCR)


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
                lang=(opts.lang if opts else "spa+eng"),
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
            SELECT docs.doc_id, docs.title, docs.author, docs.year, docs.source, docs.stored_path
            FROM docs
            {where}
            ORDER BY docs.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params_page,
        )
        rows = cur.fetchall()

    items = []
    for (doc_id, title, author, year, source, stored_path) in rows:
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
            "idioma": None,
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
            SELECT fragment_id, text, page_start FROM fragments WHERE doc_id=? ORDER BY page_start ASC, fragment_id ASC LIMIT 20
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
        from core.config_flags.feature_flags import feature_flags
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
        from core.config_flags.feature_flags import feature_flags
        
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
        from core.config_flags.feature_flags import feature_flags
        
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
