"""Stress test multi-formato: PDF + DOCX + MD.

Genera los tres documentos sintéticos, los ingiere por la API real y mide
recall sobre las frases canario embebidas en cada uno. Comprueba además que
la columna ``fragments.bbox`` se llene para PDFs (no para DOCX/TXT).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "data" / "milpa_knowledge.db"
PDF_PATH = BACKEND_ROOT / "data" / "stress_pdf_milpa.pdf"
DOCX_PATH = BACKEND_ROOT / "data" / "stress_docx_milpa.docx"
MD_PATH = BACKEND_ROOT / "data" / "stress_md_milpa.md"
REPORTS_DIR = BACKEND_ROOT / "tools" / "stress_reports"

API_INGEST = "http://127.0.0.1:8000/api/documents/ingest"
API_QUERY = "http://127.0.0.1:8000/api/query"

CANARIES = {
    "pdf": [
        ("two_col", "AGUACATILLO_DOSCOLUMNAS_CANARIO_4321", "frase canario seccion dos columnas"),
        ("three_col", "PETUNIA_TRESCOLUMNAS_CANARIO_8765", "frase canario seccion tres columnas"),
        ("table_yield", "JITOMATE_TABLA_RENDIMIENTO_CANARIO_RBR42", "marcador celda tabla rendimientos"),
        ("table_dense", "PIPILA_TABLA_DENSA_CANARIO_QWQ73", "token control cabecera tabla edafologica"),
        ("chart_legend", "CHIPILIN_FIGURA_CANARIO_LMN15", "frase canario leyenda figura"),
        ("list_item", "MEZQUITE_LISTA_CANARIO_KP9", "item numerado control manejo integrado"),
        ("footer_real", "PIE_REAL_NO_REPETIDO_99", "marca pie real no repetido"),
    ],
    "docx": [
        ("intro", "ROBLE_DOCX_INTRO_CANARIO_AB1", "introduccion del manual docx"),
        ("list", "ALAMO_DOCX_LISTA_CANARIO_CD2", "frase canario en lista bullet"),
        ("table", "ENCINA_DOCX_TABLA_CANARIO_EF3", "marca canario celda tabla rendimientos"),
        ("manage", "PINO_DOCX_MANEJO_CANARIO_GH4", "recomendaciones manejo agroecologico"),
    ],
    "md": [
        ("intro_h1", "SAUCE_MD_INTRO_CANARIO_IJ5", "introduccion del manual markdown"),
        ("h2_cult", "TARANGA_MD_CULTIVOS_CANARIO_KL6", "cultivos asociados milpa"),
        ("page2", "CIPRES_MD_MANEJO_CANARIO_MN7", "manejo agronomico segunda pagina"),
        ("fert", "FRESNO_MD_FERTILIZACION_CANARIO_OP8", "fertilizacion ajuste etapa fenologica"),
        ("page3", "JACARANDA_MD_COSECHA_CANARIO_QR9", "cosecha tercera pagina"),
    ],
}

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/plain",
    "txt": "text/plain",
}


def _http_get(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post_json(url: str, body: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ingest(file_path: Path) -> Dict[str, Any]:
    boundary = f"----milpa-stress-{int(time.time()*1000)}"
    eol = b"\r\n"
    parts: List[bytes] = []

    def field(name: str, value: str) -> None:
        parts.extend([
            f"--{boundary}".encode(), eol,
            f'Content-Disposition: form-data; name="{name}"'.encode(), eol, eol,
            value.encode("utf-8"), eol,
        ])

    ext = file_path.suffix.lstrip(".").lower()
    mime = MIME.get(ext, "application/octet-stream")
    field("license", "public_domain")
    field("classification", "Publico")
    field("title", f"MILPA stress {ext}")
    field("author", "MILPA Tools")
    field("year", "2026")
    field("chunk_size", "1200")

    parts.extend([
        f"--{boundary}".encode(), eol,
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode(),
        eol,
        f"Content-Type: {mime}".encode(), eol, eol,
        file_path.read_bytes(), eol,
        f"--{boundary}--".encode(), eol,
    ])
    body = b"".join(parts)
    req = urllib.request.Request(
        API_INGEST,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            payload = json.loads(r.read().decode("utf-8"))
            payload["_http_status"] = r.status
            payload["_elapsed_ms"] = int((time.time() - t0) * 1000)
            return payload
    except urllib.error.HTTPError as e:
        return {
            "_http_status": e.code,
            "_elapsed_ms": int((time.time() - t0) * 1000),
            "error": e.read().decode("utf-8", errors="replace"),
        }


def _existing_doc_id_by_source(source: str) -> Optional[str]:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT doc_id FROM docs WHERE source=? ORDER BY created_at DESC LIMIT 1",
        (source,),
    )
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


def _delete_doc(doc_id: str) -> None:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8000/api/documents/{doc_id}", method="DELETE"
        )
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def _reconcile() -> None:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/admin/reconcile-indexes",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass


def _query_canaries(doc_id: str, canaries: list) -> list[dict]:
    out = []
    for cid, needle, q in canaries:
        for mode in ("hybrid", "lex"):
            try:
                r = _http_post_json(
                    API_QUERY, {"query": q, "k": 8, "mode": mode}, timeout=120
                )
            except Exception as e:
                out.append({"id": cid, "mode": mode, "error": str(e)})
                continue
            frags = r.get("fragments") or []
            in_top = any(
                f.get("doc_id") == doc_id and needle in (f.get("text") or "")
                for f in frags
            )
            out.append({
                "id": cid,
                "mode": mode,
                "in_top": in_top,
                "needle": needle,
                "doc_id_in_top": [f.get("doc_id") for f in frags[:3]],
                "insufficient_evidence": r.get("insufficient_evidence"),
            })
    return out


def _bbox_audit(doc_id: str, expected_kind: str) -> dict:
    """Para PDFs verificamos que todos los fragments traigan bbox; para DOCX/TXT
    no se espera bbox (queda NULL).
    """
    if not DB_PATH.exists():
        return {}
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*), SUM(CASE WHEN bbox IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM fragments WHERE doc_id=?",
        (doc_id,),
    )
    n, n_with_bbox = cur.fetchone() or (0, 0)
    con.close()
    return {
        "kind": expected_kind,
        "fragments": n or 0,
        "with_bbox": n_with_bbox or 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="multi-formato")
    parser.add_argument("--no-regen", action="store_true")
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_regen:
        # Genera los tres
        gen_pdf = BACKEND_ROOT / "tools" / "gen_stress_pdf.py"
        gen_docx = BACKEND_ROOT / "tools" / "gen_stress_docx.py"
        gen_md = BACKEND_ROOT / "tools" / "gen_stress_md.py"
        for script, out in [(gen_pdf, PDF_PATH), (gen_docx, DOCX_PATH), (gen_md, MD_PATH)]:
            subprocess.check_call([sys.executable, str(script), "--out", str(out)])

    # Health
    health = _http_get("http://127.0.0.1:8000/health")

    # Purga previa de los tres
    for src in (PDF_PATH.name, DOCX_PATH.name, MD_PATH.name):
        prev = _existing_doc_id_by_source(src)
        if prev:
            _delete_doc(prev)
    _reconcile()

    summary = {
        "label": args.label,
        "health": health,
        "results": {},
    }

    plan = [
        ("pdf", PDF_PATH, CANARIES["pdf"]),
        ("docx", DOCX_PATH, CANARIES["docx"]),
        ("md", MD_PATH, CANARIES["md"]),
    ]

    for kind, path, canaries in plan:
        ingest = _ingest(path)
        doc_id = ingest.get("doc_id", "")
        if not doc_id:
            summary["results"][kind] = {"ingest": ingest}
            continue
        bbox = _bbox_audit(doc_id, kind)
        queries = _query_canaries(doc_id, canaries)
        passed = sum(1 for q in queries if q.get("in_top"))
        summary["results"][kind] = {
            "doc_id": doc_id,
            "ingest_status": ingest.get("_http_status"),
            "elapsed_ms": ingest.get("_elapsed_ms"),
            "pages": ingest.get("pages"),
            "fragments": ingest.get("fragments"),
            "tables": ingest.get("tables"),
            "indexed": ingest.get("indexed"),
            "bbox_audit": bbox,
            "canary_recall": f"{passed}/{len(queries)}",
            "queries": queries,
        }

    out = REPORTS_DIR / f"{args.label}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    quick = {
        kind: {
            "recall": v.get("canary_recall"),
            "frags": v.get("fragments"),
            "tables": v.get("tables"),
            "pages": v.get("pages"),
            "with_bbox": (v.get("bbox_audit") or {}).get("with_bbox"),
        }
        for kind, v in summary["results"].items()
    }
    print(json.dumps(quick, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
