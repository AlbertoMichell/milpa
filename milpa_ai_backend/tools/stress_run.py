"""Orquesta una corrida de estrés contra el backend MILPA.

Pasos:
  1. Generar (o reutilizar) el PDF sintético.
  2. POST /api/documents/ingest.
  3. Inspeccionar SQLite: páginas, fragmentos por página, fuente (native/ocr), tablas.
  4. Ejecutar /api/query con frases canario y reportar recall@k y rrf_score.
  5. Persistir reporte JSON con baseline/post-fix.

Uso:
    py -3 milpa_ai_backend/tools/stress_run.py [--label baseline] [--no-regen]
    py -3 milpa_ai_backend/tools/stress_run.py --label post-fix-1
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "data" / "milpa_knowledge.db"
PDF_PATH = BACKEND_ROOT / "data" / "stress_pdf_milpa.pdf"
REPORTS_DIR = BACKEND_ROOT / "tools" / "stress_reports"
GEN_SCRIPT = BACKEND_ROOT / "tools" / "gen_stress_pdf.py"

API_INGEST = "http://127.0.0.1:8000/api/documents/ingest"
API_QUERY = "http://127.0.0.1:8000/api/query"

CANARIES: List[Dict[str, str]] = [
    {
        "id": "two_col",
        "phrase": "AGUACATILLO_DOSCOLUMNAS_CANARIO_4321",
        "needle": "AGUACATILLO_DOSCOLUMNAS_CANARIO_4321",
        "query": "frase canario de la sección a dos columnas",
    },
    {
        "id": "three_col",
        "phrase": "PETUNIA_TRESCOLUMNAS_CANARIO_8765",
        "needle": "PETUNIA_TRESCOLUMNAS_CANARIO_8765",
        "query": "frase canario de la sección a tres columnas",
    },
    {
        "id": "table_yield",
        "phrase": "JITOMATE_TABLA_RENDIMIENTO_CANARIO_RBR42",
        "needle": "JITOMATE_TABLA_RENDIMIENTO_CANARIO_RBR42",
        "query": "marcador en celda de la tabla de rendimientos",
    },
    {
        "id": "table_dense",
        "phrase": "PIPILA_TABLA_DENSA_CANARIO_QWQ73",
        "needle": "PIPILA_TABLA_DENSA_CANARIO_QWQ73",
        "query": "token de control en la cabecera de la tabla edafológica densa",
    },
    {
        "id": "chart_legend",
        "phrase": "CHIPILIN_FIGURA_CANARIO_LMN15",
        "needle": "CHIPILIN_FIGURA_CANARIO_LMN15",
        "query": "frase canario incrustada en la leyenda de la figura",
    },
    {
        "id": "list_item",
        "phrase": "MEZQUITE_LISTA_CANARIO_KP9",
        "needle": "MEZQUITE_LISTA_CANARIO_KP9",
        "query": "ítem numerado de control para manejo integrado",
    },
    {
        "id": "footer_real",
        "phrase": "PIE_REAL_NO_REPETIDO_99",
        "needle": "PIE_REAL_NO_REPETIDO_99",
        "query": "marca de pie real que no debería filtrarse del documento",
    },
]


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


def _ingest_pdf(pdf: Path) -> Dict[str, Any]:
    boundary = f"----milpa-stress-{int(time.time()*1000)}"
    eol = b"\r\n"
    parts: List[bytes] = []

    def field(name: str, value: str) -> None:
        parts.extend(
            [
                f"--{boundary}".encode(),
                eol,
                f'Content-Disposition: form-data; name="{name}"'.encode(),
                eol,
                eol,
                value.encode("utf-8"),
                eol,
            ]
        )

    def file_field(name: str, filename: str, content: bytes, mime: str) -> None:
        parts.extend(
            [
                f"--{boundary}".encode(),
                eol,
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'
                ).encode(),
                eol,
                f"Content-Type: {mime}".encode(),
                eol,
                eol,
                content,
                eol,
            ]
        )

    field("license", "public_domain")
    field("classification", "Publico")
    field("title", "MILPA stress test sintético")
    field("author", "MILPA Tools")
    field("year", "2026")
    field("chunk_size", "1200")
    file_field(
        "file",
        pdf.name,
        pdf.read_bytes(),
        "application/pdf",
    )
    parts.append(f"--{boundary}--".encode())
    parts.append(eol)
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


def _db_inspection(doc_id: str) -> Dict[str, Any]:
    if not DB_PATH.exists():
        return {"error": "db not found"}
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out: Dict[str, Any] = {"doc_id": doc_id}
    cur.execute(
        "SELECT page_start, source, COUNT(*) AS n, SUM(LENGTH(text)) AS chars "
        "FROM fragments WHERE doc_id=? GROUP BY page_start, source ORDER BY page_start, source",
        (doc_id,),
    )
    out["fragments_by_page"] = [dict(r) for r in cur.fetchall()]
    cur.execute(
        "SELECT COUNT(*) AS n_frag, SUM(LENGTH(text)) AS chars, "
        "SUM(CASE WHEN source='native' THEN 1 ELSE 0 END) AS n_native, "
        "SUM(CASE WHEN source='ocr' THEN 1 ELSE 0 END) AS n_ocr "
        "FROM fragments WHERE doc_id=?",
        (doc_id,),
    )
    out["fragment_summary"] = dict(cur.fetchone())
    cur.execute(
        "SELECT COUNT(*) AS n_tables, SUM(LENGTH(csv)) AS csv_bytes "
        "FROM tables WHERE doc_id=?",
        (doc_id,),
    )
    out["tables"] = dict(cur.fetchone())
    canary_hits = []
    for c in CANARIES:
        cur.execute(
            "SELECT fragment_id, page_start, LENGTH(text) AS chars, source "
            "FROM fragments WHERE doc_id=? AND text LIKE ? LIMIT 3",
            (doc_id, f"%{c['needle']}%"),
        )
        rows = [dict(r) for r in cur.fetchall()]
        canary_hits.append({"id": c["id"], "needle": c["needle"], "hits": rows})
    out["canary_in_fragments"] = canary_hits
    con.close()
    return out


def _run_queries(doc_id: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for c in CANARIES:
        for mode in ("hybrid", "lex"):
            t0 = time.time()
            try:
                r = _http_post_json(
                    API_QUERY,
                    {"query": c["query"], "k": 8, "mode": mode},
                    timeout=120,
                )
            except urllib.error.HTTPError as e:
                results.append(
                    {
                        "canary_id": c["id"],
                        "mode": mode,
                        "error": f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}",
                    }
                )
                continue
            except Exception as e:
                results.append({"canary_id": c["id"], "mode": mode, "error": str(e)})
                continue
            frags = r.get("fragments", []) or []
            hit_idx = -1
            for i, f in enumerate(frags):
                if c["needle"] in (f.get("text") or ""):
                    hit_idx = i
                    break
            results.append(
                {
                    "canary_id": c["id"],
                    "mode": mode,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "insufficient_evidence": r.get("insufficient_evidence"),
                    "rank_of_canary": hit_idx,
                    "top_scores": [round(float(f.get("score") or 0.0), 5) for f in frags[:5]],
                    "doc_id_in_top": [
                        f.get("doc_id") for f in frags[:5]
                    ],
                    "canary_in_top_doc": any(
                        f.get("doc_id") == doc_id and c["needle"] in (f.get("text") or "")
                        for f in frags
                    ),
                }
            )
    return results


def _delete_existing_doc(doc_id: str) -> None:
    """Borra un doc usando el endpoint DELETE /api/documents/{doc_id} si está
    disponible. Cae a borrado directo en SQLite si la API no responde."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8000/api/documents/{doc_id}", method="DELETE"
        )
        urllib.request.urlopen(req, timeout=15).read()
        return
    except Exception:
        pass

    if not DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT table_id FROM tables WHERE doc_id=?", (doc_id,))
    for (tid,) in cur.fetchall():
        cur.execute("DELETE FROM table_cells WHERE table_id=?", (tid,))
    cur.execute("DELETE FROM tables WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM fragments WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM licenses WHERE doc_id=?", (doc_id,))
    con.commit()
    con.close()


def _reconcile_indexes() -> Dict[str, Any]:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/admin/reconcile-indexes",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=b"{}",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


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


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--no-regen", action="store_true")
    parser.add_argument(
        "--no-purge",
        action="store_true",
        help="No borrar el documento previo con el mismo source antes de re-ingestar",
    )
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_regen or not PDF_PATH.exists():
        subprocess.check_call([sys.executable, str(GEN_SCRIPT), "--out", str(PDF_PATH)])

    if not args.no_purge:
        prev = _existing_doc_id_by_source(PDF_PATH.name)
        if prev:
            _delete_existing_doc(prev)
        # Reconciliación de índices: purga doc_ids huérfanos en BM25/Chroma
        # que ya no estén en SQLite (ruido acumulado de corridas previas).
        _reconcile_indexes()

    health = _http_get("http://127.0.0.1:8000/health")
    ingest = _ingest_pdf(PDF_PATH)
    doc_id = ingest.get("doc_id", "")

    if not doc_id:
        report = {
            "label": args.label,
            "health": health,
            "ingest": ingest,
        }
        out = REPORTS_DIR / f"{args.label}.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    db = _db_inspection(doc_id)
    queries = _run_queries(doc_id)

    canary_hits = sum(1 for q in queries if q.get("canary_in_top_doc"))
    canary_total = len(queries)
    summary = {
        "doc_id": doc_id,
        "ingest_status": ingest.get("_http_status"),
        "ingest_elapsed_ms": ingest.get("_elapsed_ms"),
        "pages": ingest.get("pages"),
        "fragments": ingest.get("fragments"),
        "tables": ingest.get("tables"),
        "indexed": ingest.get("indexed"),
        "canary_recall_in_top": f"{canary_hits}/{canary_total}",
    }

    report = {
        "label": args.label,
        "health": health,
        "ingest": ingest,
        "db": db,
        "queries": queries,
        "summary": summary,
    }
    out = REPORTS_DIR / f"{args.label}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
