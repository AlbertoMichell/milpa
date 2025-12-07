from __future__ import annotations

import sqlite3
from pathlib import Path


DB = Path(__file__).resolve().parent.parent / "data" / "milpa_knowledge.db"
PDF = Path(__file__).resolve().parent.parent / "data" / "documents" / "demo_biblioteca_tablas.pdf"


def ensure_entry():
    if not PDF.exists():
        print(f"No existe el PDF esperado: {PDF}")
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
              doc_id TEXT PRIMARY KEY,
              title TEXT, author TEXT, year INT, source TEXT, hash TEXT,
              license TEXT, lang_original TEXT, classification TEXT, created_at TEXT,
              stored_path TEXT
            )
            """
        )
        cur.execute("SELECT 1 FROM docs WHERE doc_id=?", ("demo-pdf-2",))
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO docs (doc_id, title, author, year, source, hash, license, lang_original, classification, created_at, stored_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                """,
                (
                    "demo-pdf-2",
                    "MILPA • Tablas de prueba (PDF)",
                    "Equipo MILPA",
                    2025,
                    PDF.name,
                    "demo-pdf-2",
                    "public_domain",
                    "es",
                    "Publico",
                    str(PDF.resolve()),
                ),
            )
            conn.commit()
            print("Insertado demo-pdf-2 en docs")
        else:
            print("demo-pdf-2 ya existía en docs")

        # Asegurar tabla de tablas
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tables (
              table_id TEXT PRIMARY KEY,
              doc_id TEXT,
              page INT,
              bbox TEXT,
              csv TEXT,
              schema JSON
            )
            """
        )
        # Insertar una tabla de ejemplo si no existe
        cur.execute("SELECT 1 FROM tables WHERE table_id=?", ("demo-table-1",))
        if cur.fetchone() is None:
            csv_text = "Cultivo,Region,Rendimiento\nMaiz,Centro,7.2\nFrijol,Norte,1.8\nCalabaza,Occidente,12.3"
            cur.execute(
                """
                INSERT INTO tables (table_id, doc_id, page, bbox, csv, schema)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("demo-table-1", "demo-pdf-2", 1, "[]", csv_text, None),
            )
            conn.commit()
            print("Insertada tabla demo-table-1 para demo-pdf-2")
    finally:
        conn.close()


if __name__ == "__main__":
    ensure_entry()
