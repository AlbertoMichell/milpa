"""Sube el PDF de Lechuga al backend e inspecciona el extractor block-level.

Reporta:
  - doc_id devuelto por /api/documents/ingest
  - cantidad de fragmentos en SQLite
  - cobertura de bbox real (no degenerado, no full-page)
  - distribución de tokens por fragmento (verifica EXTRACT_TARGET_TOKENS)
  - render PNG con overlays para inspección visual

Uso:
    py -3 milpa_ai_backend/tools/ingest_lechuga_pdf.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "milpa_ai_backend" / "data" / "milpa_knowledge.db"
PDF_PATH = ROOT / "docs" / "manual_lechuga_milpa_2026.pdf"
BACKEND = "http://127.0.0.1:8000"
REPORT_DIR = ROOT / "milpa_ai_backend" / "tools" / "stress_reports"


def _multipart_upload(path: Path, mime: str = "application/pdf") -> dict:
    boundary = "----milpaLechuga"
    fname = path.name
    content = path.read_bytes()
    body = (
        f"--{boundary}\r\n".encode()
        + f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
        + f"Content-Type: {mime}\r\n\r\n".encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        BACKEND + "/api/documents/ingest",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def _existing_doc_id(source_filename: str) -> str | None:
    with sqlite3.connect(str(DB_PATH)) as c:
        row = c.execute(
            "SELECT doc_id FROM docs WHERE source LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"%{source_filename}",),
        ).fetchone()
    return row[0] if row else None


def _delete_doc(doc_id: str) -> None:
    req = urllib.request.Request(
        BACKEND + f"/api/documents/{doc_id}", method="DELETE"
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def _reconcile() -> None:
    req = urllib.request.Request(
        BACKEND + "/api/admin/reconcile-indexes", method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def _audit(doc_id: str) -> dict:
    with sqlite3.connect(str(DB_PATH)) as c:
        n_frags = c.execute(
            "SELECT COUNT(*) FROM fragments WHERE doc_id=?", (doc_id,)
        ).fetchone()[0]
        n_tables = c.execute(
            "SELECT COUNT(*) FROM tables WHERE doc_id=?", (doc_id,)
        ).fetchone()[0]
        rows = c.execute(
            "SELECT fragment_id, page_start, bbox, char_count, source FROM fragments "
            "WHERE doc_id=? ORDER BY page_start, seq",
            (doc_id,),
        ).fetchall()
    valid_bbox = 0
    page_full_bbox = 0  # bbox que es la página completa = no es block-level
    char_counts: list[int] = []
    page_dist: dict[int, int] = {}
    for fid, page, bb, cc, src in rows:
        page_dist[page] = page_dist.get(page, 0) + 1
        if cc:
            char_counts.append(int(cc))
        if not bb:
            continue
        try:
            x0, y0, x1, y1 = json.loads(bb)
        except Exception:
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        valid_bbox += 1
        # heurística: si bbox cubre ≥95% del área de página letter (612x792), es full
        if (x1 - x0) >= 580 and (y1 - y0) >= 750:
            page_full_bbox += 1
    return {
        "doc_id": doc_id,
        "fragments": n_frags,
        "tables": n_tables,
        "fragments_with_valid_bbox": valid_bbox,
        "fragments_with_full_page_bbox": page_full_bbox,
        "fragments_with_block_bbox": valid_bbox - page_full_bbox,
        "char_count_stats": {
            "min": min(char_counts) if char_counts else 0,
            "max": max(char_counts) if char_counts else 0,
            "avg": (sum(char_counts) / len(char_counts)) if char_counts else 0,
        },
        "fragments_per_page": page_dist,
        "sample_first_3": [
            {"fragment_id": r[0], "page": r[1], "bbox": (json.loads(r[2]) if r[2] else None), "chars": r[3], "source": r[4]}
            for r in rows[:3]
        ],
    }


def _render_overlay(doc_id: str, page: int = 1) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"render_lechuga_p{page}_overlays.png"
    url = f"{BACKEND}/api/documents/{doc_id}/render?page={page}&highlight_all=true&scale=2.0"
    with urllib.request.urlopen(url, timeout=30) as r:
        out.write_bytes(r.read())
    return out


def main() -> int:
    if not PDF_PATH.exists():
        print(f"ERROR: PDF no existe en {PDF_PATH}")
        return 2
    print(f"PDF source: {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
    # Limpiar duplicados previos (mismo nombre de archivo)
    prev = _existing_doc_id("manual_lechuga_milpa_2026.pdf")
    if prev:
        print(f"  Documento previo encontrado ({prev[:12]}…), eliminando…")
        _delete_doc(prev)
    _reconcile()

    payload = _multipart_upload(PDF_PATH)
    doc_id = payload.get("doc_id") or payload.get("doc", {}).get("doc_id")
    print(f"INGEST RESPONSE: {json.dumps(payload, indent=2, ensure_ascii=False)[:600]}")
    if not doc_id:
        print("FAIL: no se obtuvo doc_id")
        return 1
    audit = _audit(doc_id)
    print("\nAUDIT BLOCK-LEVEL:")
    print(json.dumps(audit, indent=2, ensure_ascii=False, default=str))

    print("\nRENDER OVERLAYS:")
    for p in range(1, min(audit["fragments_per_page"] and max(audit["fragments_per_page"].keys()) or 1, 3) + 1):
        try:
            png = _render_overlay(doc_id, p)
            print(f"  page {p}: {png}")
        except Exception as e:
            print(f"  page {p}: ERROR {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
