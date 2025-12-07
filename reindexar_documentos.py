import requests
import time
from pathlib import Path

# Documentos a reindexar
documentos = [
    "milpa_ai_backend/data/documents/fertilizacion_frijol_arcilloso.txt",
    "milpa_ai_backend/data/documents/nutrientes_maiz.txt",
    "milpa_ai_backend/data/documents/plagas_tomate_tropical.txt",
]

API_URL = "http://localhost:8000"

print("=== REINDEXACIÓN DE DOCUMENTOS AGRÍCOLAS ===\n")

for doc_path in documentos:
    doc_file = Path(doc_path)
    if not doc_file.exists():
        print(f"❌ No encontrado: {doc_path}")
        continue
    
    print(f"📄 Subiendo: {doc_file.name}")
    
    # 1. Upload
    with open(doc_file, 'rb') as f:
        files = {'file': (doc_file.name, f, 'text/plain')}
        data = {
            'license': 'institutional',
            'classification': 'Interno'
        }
        
        try:
            response = requests.post(
                f"{API_URL}/api/documents/upload",
                files=files,
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                doc_id = result.get('doc_id')
                print(f"   ✓ Upload OK - doc_id: {doc_id[:16]}...")
                
                # 2. Extract
                print(f"   → Extrayendo fragmentos...")
                extract_response = requests.post(
                    f"{API_URL}/api/documents/{doc_id}/extract",
                    timeout=60
                )
                
                if extract_response.status_code == 200:
                    extract_result = extract_response.json()
                    n_fragments = extract_result.get('n_fragments', 0)
                    print(f"   ✓ Extracción OK - {n_fragments} fragmentos")
                else:
                    print(f"   ❌ Error extracción: {extract_response.status_code}")
                    print(f"      {extract_response.text}")
            else:
                print(f"   ❌ Error upload: {response.status_code}")
                print(f"      {response.text}")
        
        except Exception as e:
            print(f"   ❌ Excepción: {e}")
    
    time.sleep(1)  # Pausa entre documentos

print("\n=== VERIFICACIÓN FINAL ===")

# Consultar estado de la base de datos
import sqlite3
conn = sqlite3.connect('milpa_ai_backend/data/milpa_knowledge.db')
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM docs")
n_docs = cursor.fetchone()[0]
print(f"Documentos en BD: {n_docs}")

cursor.execute("SELECT COUNT(*) FROM fragments")
n_frags = cursor.fetchone()[0]
print(f"Fragmentos en BD: {n_frags}")

cursor.execute("SELECT source FROM docs ORDER BY created_at DESC LIMIT 5")
recent = cursor.fetchall()
print(f"\nÚltimos documentos:")
for r in recent:
    print(f"  - {r[0]}")

conn.close()
