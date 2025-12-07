"""
Script para crear BD de tests con migraciones aplicadas
"""
import sqlite3
from pathlib import Path

def crear_bd_tests():
    # Ruta de la BD
    db_path = Path("milpa_ai_backend/data/test_contract.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Conectar a BD
    conn = sqlite3.connect(db_path)
    
    # Aplicar migraciones
    migrations_dir = Path("milpa_ai_backend/core/logic/migrations")
    sql_files = sorted(migrations_dir.glob("*.sql"))
    
    for sql_file in sql_files:
        print(f"  Aplicando: {sql_file.name}")
        with open(sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
            # Filtrar comentarios con #
            lines = [l for l in sql.split('\n') if not l.strip().startswith('#')]
            sql_clean = '\n'.join(lines)
            if sql_clean.strip():
                conn.executescript(sql_clean)
    
    conn.commit()
    conn.close()
    print("✅ BD de tests creada exitosamente")

if __name__ == "__main__":
    crear_bd_tests()
