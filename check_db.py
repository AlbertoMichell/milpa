import sqlite3

conn = sqlite3.connect('milpa_ai_backend/data/milpa_knowledge.db')
cursor = conn.cursor()

# Listar tablas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("=== TABLAS EN LA BASE DE DATOS ===")
for t in tables:
    print(f"  - {t[0]}")

print("\n=== CONTENIDO DE CADA TABLA ===")
for table in tables:
    table_name = table[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"\n{table_name}: {count} registros")
    
    if count > 0 and count < 20:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
        rows = cursor.fetchall()
        for row in rows:
            print(f"  {row}")

conn.close()
