import sqlite3
db = r'milpa_ai_backend\data\milpa_knowledge.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print('TABLAS:', tables)
for t in tables:
    cur.execute("PRAGMA table_info(" + t + ")")
    cols = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM " + t)
    count = cur.fetchone()[0]
    print("\n--- " + t + " (" + str(count) + " filas) ---")
    for c in cols:
        pk = " PK" if c[5] else ""
        nn = " NOT NULL" if c[3] else ""
        print("  " + c[1] + " " + str(c[2]) + pk + nn)
conn.close()
