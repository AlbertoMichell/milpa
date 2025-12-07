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
