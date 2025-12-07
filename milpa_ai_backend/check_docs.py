import sqlite3
conn = sqlite3.connect('data/main.db')
cur = conn.cursor()
cur.execute('SELECT doc_id, title, source, stored_path FROM docs')
print("Documentos registrados:")
print("=" * 80)
for row in cur.fetchall():
    doc_id, title, source, stored_path = row
    print(f"Title: {title}")
    print(f"  doc_id: {doc_id[:16]}...")
    print(f"  source: {source}")
    print(f"  stored_path: {stored_path if stored_path else 'NULL'}")
    print()
conn.close()
