#!/usr/bin/env python3
"""
Script para procesar archivos TXT e insertarlos como fragmentos en la BD.
Los PDFs se procesarán después con el endpoint de extracción.
"""

import sqlite3
import hashlib
from pathlib import Path
import uuid

def main():
    db_path = Path("data/main.db")
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    
    # Obtener todos los documentos TXT
    cur.execute('''
        SELECT doc_id, title, source, stored_path 
        FROM docs 
        WHERE source LIKE '%.txt' OR source LIKE '%.tx'
    ''')
    txt_docs = cur.fetchall()
    
    print(f"Encontrados {len(txt_docs)} documentos TXT")
    print("=" * 60)
    
    for doc_id, title, source, stored_path in txt_docs:
        print(f"\nProcesando: {source}")
        
        # Verificar si ya tiene fragmentos
        cur.execute('SELECT COUNT(*) FROM fragments WHERE doc_id=?', (doc_id,))
        if cur.fetchone()[0] > 0:
            print(f"  ⏭  Ya tiene fragmentos, omitiendo...")
            continue
        
        # Leer contenido del archivo
        try:
            file_path = Path(stored_path)
            if not file_path.exists():
                print(f"  ✗ Archivo no encontrado: {stored_path}")
                continue
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content:
                print(f"  ⚠  Archivo vacío")
                continue
            
            # Crear fragmento único
            fragment_id = str(uuid.uuid4())
            fragment_uid = hashlib.md5(content.encode()).hexdigest()[:16]
            
            cur.execute('''
                INSERT INTO fragments 
                (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end, text, text_es, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                fragment_id,
                doc_id,
                fragment_uid,
                'txt_content',
                1,
                1,
                content,
                content,  # Asumimos que está en español
                'native',
            ))
            
            conn.commit()
            print(f"  ✓ Fragmento creado ({len(content)} caracteres)")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            conn.rollback()
    
    conn.close()
    print("\n" + "=" * 60)
    print("Procesamiento de archivos TXT completado")


if __name__ == "__main__":
    main()
