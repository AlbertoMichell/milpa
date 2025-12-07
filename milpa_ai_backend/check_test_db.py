import sqlite3
import os

db = os.environ.get('SQLITE_PATH', '/tmp/milpa_knowledge_test.db')
print(f'BD test: {db}')

if not os.path.exists(db):
    print('BD no existe')
else:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = [t[0] for t in cur.fetchall()]
    print(f'Tablas: {tables}')
    
    if 'fragments' in tables:
        cur.execute('SELECT COUNT(*) FROM fragments')
        print(f'Fragments: {cur.fetchone()[0]}')
    
    conn.close()
