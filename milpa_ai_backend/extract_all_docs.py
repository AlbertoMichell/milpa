#!/usr/bin/env python3
"""
Script para ejecutar extracción de contenido de todos los documentos registrados.
Llama al endpoint /api/documents/{doc_id}/extract para cada documento.
"""

import sqlite3
import sys
import requests
from pathlib import Path
import time

def main():
    # Conectar a la BD
    db_path = Path("data/main.db")
    if not db_path.exists():
        print(f"ERROR: Base de datos no encontrada: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    
    # Obtener todos los documentos
    cur.execute('SELECT doc_id, title, source FROM docs ORDER BY created_at')
    docs = cur.fetchall()
    conn.close()
    
    if not docs:
        print("No hay documentos registrados en la base de datos")
        sys.exit(0)
    
    print(f"Encontrados {len(docs)} documentos para extraer contenido")
    print("=" * 60)
    
    base_url = "http://localhost:8000"
    extracted = 0
    skipped = 0
    errors = 0
    
    for doc_id, title, source in docs:
        print(f"\nProcesando: {source}")
        print(f"  doc_id: {doc_id[:12]}...")
        print(f"  title: {title}")
        
        # Verificar si ya tiene fragmentos extraídos
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM fragments WHERE doc_id=?', (doc_id,))
        count = cur.fetchone()[0]
        conn.close()
        
        if count > 0:
            print(f"  ⏭  Ya tiene {count} fragmentos extraídos, omitiendo...")
            skipped += 1
            continue
        
        # Ejecutar extracción
        try:
            url = f"{base_url}/api/documents/{doc_id}/extract"
            print(f"  🔄 Extrayendo contenido...")
            
            # Configuración de extracción
            payload = {
                "ocr_missing_text": True,
                "extract_tables": "auto",
                "chunk_size": 1200,
                "lang": "spa+eng"
            }
            
            response = requests.post(url, json=payload, timeout=120)
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Extracción exitosa:")
                print(f"    - Páginas: {result.get('pages_processed', 0)}")
                print(f"    - Fragmentos: {result.get('fragments_created', 0)}")
                print(f"    - Tablas: {result.get('tables_created', 0)}")
                extracted += 1
            else:
                print(f"  ✗ Error HTTP {response.status_code}: {response.text[:200]}")
                errors += 1
        
        except requests.exceptions.Timeout:
            print(f"  ✗ Timeout (>120s) - documento muy grande o OCR lento")
            errors += 1
        except requests.exceptions.ConnectionError:
            print(f"  ✗ Error de conexión - ¿Backend corriendo en {base_url}?")
            errors += 1
            break
        except Exception as e:
            print(f"  ✗ Error inesperado: {e}")
            errors += 1
        
        # Pequeña pausa entre documentos
        time.sleep(0.5)
    
    print("\n" + "=" * 60)
    print("Resumen de extracción:")
    print(f"  ✓ Extraídos: {extracted}")
    print(f"  ⏭  Ya procesados: {skipped}")
    print(f"  ✗ Errores: {errors}")
    print(f"  Total documentos: {len(docs)}")


if __name__ == "__main__":
    main()
