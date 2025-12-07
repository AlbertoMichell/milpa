#!/usr/bin/env python3
"""
Script para indexar documentos existentes en data/documents/
Registra metadatos en BD y luego ejecuta extracción de contenido.
"""

import sqlite3
import sys
from pathlib import Path
import hashlib

def calculate_sha256(file_path: Path) -> str:
    """Calcula SHA-256 de un archivo."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def main():
    # Conectar a la BD
    db_path = Path("data/main.db")
    if not db_path.exists():
        print(f"ERROR: Base de datos no encontrada: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    
    # Directorio de documentos
    docs_dir = Path("data/documents")
    if not docs_dir.exists():
        print(f"ERROR: Directorio no encontrado: {docs_dir}")
        sys.exit(1)
    
    # Procesar solo archivos .txt y .pdf
    files_to_process = []
    for ext in ['.txt', '.pdf']:
        files_to_process.extend(docs_dir.glob(f'*{ext}'))
    
    print(f"Encontrados {len(files_to_process)} archivos (.txt, .pdf)")
    print("=" * 60)
    
    registered = 0
    skipped = 0
    
    for file_path in sorted(files_to_process):
        # Calcular doc_id (SHA-256)
        try:
            doc_id = calculate_sha256(file_path)
        except Exception as e:
            print(f"✗ Error calculando hash de {file_path.name}: {e}")
            continue
        
        # Verificar si ya existe
        cur.execute('SELECT doc_id FROM docs WHERE doc_id=?', (doc_id,))
        if cur.fetchone():
            print(f"⏭  Ya existe: {file_path.name} (doc_id: {doc_id[:12]}...)")
            skipped += 1
            continue
        
        # Extraer título del nombre del archivo
        file_name = file_path.name
        if '__' in file_name:
            # Formato: timestamp__nombre.ext
            title = file_name.split('__', 1)[1].rsplit('.', 1)[0]
        else:
            # Formato: nombre.ext
            title = file_name.rsplit('.', 1)[0]
        
        stored_path = str(file_path.resolve())
        
        # Insertar en docs
        try:
            cur.execute('''
                INSERT INTO docs 
                (doc_id, title, author, year, source, hash, license, classification, created_at, stored_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
            ''', (
                doc_id,
                title,
                'Sistema',
                2025,
                file_name,
                doc_id,
                'institutional',
                'Interno',
                stored_path
            ))
            
            # Insertar en licenses
            cur.execute('''
                INSERT INTO licenses (doc_id, license, checked_by, checked_at)
                VALUES (?, ?, ?, datetime('now'))
            ''', (doc_id, 'institutional', 'batch_import'))
            
            conn.commit()
            print(f"✓ Registrado: {file_name}")
            print(f"  doc_id: {doc_id[:12]}...")
            print(f"  title: {title}")
            registered += 1
            
        except Exception as e:
            print(f"✗ Error registrando {file_name}: {e}")
            conn.rollback()
    
    conn.close()
    
    print("=" * 60)
    print(f"Resumen:")
    print(f"  Registrados: {registered}")
    print(f"  Ya existían: {skipped}")
    print(f"  Total procesados: {len(files_to_process)}")
    print()
    print("Siguiente paso: Ejecutar extracción para cada documento con:")
    print("  curl -X POST http://localhost:8000/api/documents/<doc_id>/extract")


if __name__ == "__main__":
    main()
