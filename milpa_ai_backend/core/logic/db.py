# milpa_ai_backend/core/logic/db.py
# Abstracción simple para conexión SQLite y ejecución de migraciones con yoyo.
import sqlite3
from pathlib import Path

from yoyo import read_migrations, get_backend
from milpa_ai_backend.core.config import settings

def get_conn() -> sqlite3.Connection:
    """
    Retorna una conexión SQLite. Asegura la existencia del directorio.
    """
    db_path = Path(settings.SQLITE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    # Mejor rendimiento/consistencia en concurrencia moderada:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def _backfill_fragment_seq() -> None:
    """
    Asigna seq 0,1,2,… por documento en orden lógico (página, orden de inserción).
    Antes seq existía, rowid aproxima el orden de inserción; UUID no lo preserva.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(fragments)")
            if "seq" not in {r[1] for r in cur.fetchall()}:
                return
        except Exception:
            return
        cur.execute("SELECT COUNT(*) FROM fragments WHERE seq IS NULL")
        if cur.fetchone()[0] == 0:
            return
        cur.execute(
            "SELECT doc_id, fragment_id, rowid FROM fragments ORDER BY doc_id, page_start, rowid"
        )
        rows = cur.fetchall()
        n_by_doc: dict = {}
        for doc_id, fid, _ in rows:
            n = n_by_doc.get(doc_id, 0)
            cur.execute("UPDATE fragments SET seq = ? WHERE fragment_id = ?", (n, fid))
            n_by_doc[doc_id] = n + 1
        conn.commit()


def run_migrations():
    """
    Ejecuta migraciones idempotentes con yoyo (sólo si hay cambios).
    """
    db_url = f"sqlite:///{settings.SQLITE_PATH}"
    backend = get_backend(db_url)
    migrations_path = Path(__file__).parent / "migrations"
    migrations = read_migrations(str(migrations_path))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    _backfill_fragment_seq()
