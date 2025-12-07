#!/usr/bin/env python3
"""Verificar fragmentos en la base de datos"""
import sqlite3
from pathlib import Path

db_path = Path("data/main.db")
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

cur.execute('''
    SELECT f.fragment_id, f.doc_id, d.title, 
           substr(f.text, 1, 80) as preview, 
           length(f.text) as len,
           f.created_at
    FROM fragments f
    JOIN docs d ON f.doc_id = d.doc_id
    ORDER BY f.created_at DESC
''')

rows = cur.fetchall()
print(f"Total fragmentos: {len(rows)}\n")
print("=" * 120)
for fragment_id, doc_id, title, preview, length, created_at in rows:
    print(f"Doc: {title}")
    print(f"  Fragment ID: {fragment_id}")
    print(f"  Length: {length} chars")
    print(f"  Preview: {preview}...")
    print(f"  Created: {created_at}")
    print()

conn.close()
