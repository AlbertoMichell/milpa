"""
Elimina un documento por doc_id (SQLite + archivos opcionales) y reconstruye BM25 + vector.
Uso: py -3 delete_doc_and_reindex.py <doc_id> [--no-rebuild] [--no-delete-files]
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Raíz del repo: .../milpa
REPO = Path(__file__).resolve().parents[2]
DB = REPO / "milpa_ai_backend" / "data" / "milpa_knowledge.db"


def remove_doc_rows(conn: sqlite3.Connection, doc_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM table_cells WHERE table_id IN (SELECT table_id FROM tables WHERE doc_id=?)",
        (doc_id,),
    )
    cur.execute("DELETE FROM tables WHERE doc_id=?", (doc_id,))
    cur.execute(
        "DELETE FROM fine_refs WHERE fragment_id IN (SELECT fragment_id FROM fragments WHERE doc_id=?)",
        (doc_id,),
    )
    cur.execute("DELETE FROM figures WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM fragments WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM licenses WHERE doc_id=?", (doc_id,))
    cur.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print("Falta doc_id", file=sys.stderr)
        return 1
    doc_id = args[0]
    no_rebuild = "--no-rebuild" in flags
    no_delete_files = "--no-delete-files" in flags

    if not DB.exists():
        print("No existe", DB, file=sys.stderr)
        return 1

    stored: str | None = None
    with sqlite3.connect(str(DB)) as conn:
        row = conn.execute("SELECT stored_path, source FROM docs WHERE doc_id=?", (doc_id,)).fetchone()
        if not row:
            print("doc_id no encontrado:", doc_id, file=sys.stderr)
            return 1
        stored, _source = row[0], row[1]
        remove_doc_rows(conn, doc_id)
        conn.commit()
        print("Filas eliminadas para", doc_id)

    if not no_delete_files and stored:
        p = Path(stored)
        if p.is_file():
            p.unlink()
            print("Archivo eliminado:", p)

    if not no_rebuild:
        # Import after cwd / PYTHONPATH
        sys.path.insert(0, str(REPO))
        os.chdir(str(REPO))
        from milpa_ai_backend.api.rag import rebuild_indexes
        import asyncio

        try:
            asyncio.run(rebuild_indexes())
            print("Índices reconstruidos.")
        except Exception as e:
            print("Rebuild:", e, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
