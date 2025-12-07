#!/usr/bin/env python3
"""
Test funcional del sistema RAG de MILPA.
Verifica que la consulta RAG esté operativa y no sea solo decorativa.
"""
import sys
import sqlite3
import requests
import json
from pathlib import Path

# Configuración
BASE_URL = "http://localhost:8000"
DB_PATH = "data/milpa_knowledge.db"

def check_backend_health():
    """Verifica que el backend esté corriendo."""
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code == 200:
            print("✓ Backend está corriendo")
            return True
        else:
            print(f"✗ Backend devolvió status {resp.status_code}")
            return False
    except Exception as e:
        print(f"✗ No se puede conectar al backend: {e}")
        return False

def check_database():
    """Verifica el estado de la base de datos."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM docs")
        num_docs = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM fragments")
        num_fragments = cur.fetchone()[0]
        
        conn.close()
        
        print(f"✓ Base de datos: {num_docs} documentos, {num_fragments} fragmentos")
        return num_docs, num_fragments
    except Exception as e:
        print(f"✗ Error al leer la BD: {e}")
        return 0, 0

def insert_test_data():
    """Inserta datos de prueba si no existen."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Insertar documento de prueba
    doc_id = "test_doc_001"
    cur.execute("""
        INSERT OR IGNORE INTO docs (doc_id, title, author, year, source, hash, license, lang_original, classification, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (doc_id, "Manual de Fertilización de Maíz", "INTA", 2024, "test_manual.pdf", doc_id, "institutional", "es", "Publico"))
    
    # Insertar fragmentos de prueba con contenido agrícola
    fragments = [
        {
            "fragment_id": "frag_001",
            "text": "La fertilización nitrogenada en maíz debe aplicarse en dosis de 150-200 kg/ha de N, fraccionada en dos aplicaciones: 50% en siembra y 50% en V6-V8. Para suelos arcillosos, se recomienda la forma amoniacal para reducir pérdidas por lixiviación.",
            "page_start": 12,
            "page_end": 12
        },
        {
            "fragment_id": "frag_002", 
            "text": "El fósforo (P2O5) en dosis de 80-100 kg/ha debe aplicarse completamente en siembra, incorporado al suelo. La deficiencia de fósforo causa coloración púrpura en hojas jóvenes y retraso en el desarrollo radicular.",
            "page_start": 15,
            "page_end": 15
        },
        {
            "fragment_id": "frag_003",
            "text": "Para el control de plagas en tomate, especialmente Tuta absoluta, se recomienda aplicar spinosad 120 SC a dosis de 60-80 ml/ha. El monitoreo debe realizarse semanalmente mediante trampas de feromonas.",
            "page_start": 23,
            "page_end": 23
        },
        {
            "fragment_id": "frag_004",
            "text": "La etapa fenológica V6 en maíz corresponde a 6 hojas completamente desarrolladas, aproximadamente 30-35 días después de siembra. Esta es una etapa crítica para la aplicación de nitrógeno de cobertura.",
            "page_start": 8,
            "page_end": 8
        },
        {
            "fragment_id": "frag_005",
            "text": "El potasio (K2O) es esencial para la resistencia a enfermedades y calidad de grano. Se recomienda 100-120 kg/ha en suelos con bajo contenido de K intercambiable (<150 ppm).",
            "page_start": 17,
            "page_end": 17
        }
    ]
    
    for frag in fragments:
        cur.execute("""
            INSERT OR IGNORE INTO fragments (fragment_id, doc_id, fragment_uid, section_id, page_start, page_end, text, text_es, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            frag["fragment_id"],
            doc_id,
            frag["fragment_id"],
            "section_1",
            frag["page_start"],
            frag["page_end"],
            frag["text"],
            frag["text"],
            "native",
        ))
    
    conn.commit()
    conn.close()
    
    print(f"✓ Insertados 1 documento y {len(fragments)} fragmentos de prueba")

def rebuild_indexes():
    """Reconstruye los índices BM25 y vectoriales."""
    try:
        print("→ Reconstruyendo índices...")
        resp = requests.post(f"{BASE_URL}/api/index/rebuild", timeout=60)
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ Índices reconstruidos: {data.get('indexed_fragments', 0)} fragmentos indexados")
            return True
        else:
            print(f"✗ Error al reconstruir índices: {resp.status_code}")
            print(f"  Respuesta: {resp.text}")
            return False
    except Exception as e:
        print(f"✗ Error en rebuild: {e}")
        return False

def test_rag_query(query: str, expected_keywords: list = None):
    """Ejecuta una consulta RAG y verifica la respuesta."""
    print(f"\n→ Consultando: '{query}'")
    
    try:
        payload = {
            "query": query,
            "k": 5,
            "mode": "hybrid"
        }
        
        resp = requests.post(
            f"{BASE_URL}/api/query",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if resp.status_code != 200:
            print(f"✗ Error HTTP {resp.status_code}: {resp.text}")
            return False
        
        data = resp.json()
        
        # Verificar estructura de respuesta
        print(f"  Total recuperados: {data.get('total_retrieved', 0)}")
        print(f"  Modo: {data.get('mode', 'N/A')}")
        print(f"  Evidencia insuficiente: {data.get('insufficient_evidence', False)}")
        
        fragments = data.get('fragments', [])
        if not fragments:
            print("  ✗ No se recuperaron fragmentos")
            return False
        
        print(f"\n  Fragmentos recuperados:")
        for i, frag in enumerate(fragments[:3], 1):
            print(f"    {i}. [Score: {frag.get('score', 0):.3f}] {frag.get('text', '')[:100]}...")
        
        # Verificar respuesta generada
        answer = data.get('answer')
        if answer:
            print(f"\n  Respuesta generada ({data.get('answer_mode', 'N/A')}):")
            print(f"    {answer[:300]}...")
        else:
            print("  ⚠ No se generó respuesta (posible: generador no disponible)")
        
        # Verificar keywords esperados
        if expected_keywords:
            found_keywords = []
            all_text = " ".join([f.get('text', '') for f in fragments])
            
            for kw in expected_keywords:
                if kw.lower() in all_text.lower():
                    found_keywords.append(kw)
            
            print(f"\n  Keywords encontrados: {len(found_keywords)}/{len(expected_keywords)}")
            for kw in found_keywords:
                print(f"    ✓ '{kw}'")
            
            if len(found_keywords) == 0:
                print("  ✗ Ningún keyword esperado encontrado")
                return False
        
        print("  ✓ Consulta RAG funcional")
        return True
        
    except Exception as e:
        print(f"✗ Error en consulta: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Ejecuta la suite de tests."""
    print("=" * 70)
    print("TEST FUNCIONAL - Sistema RAG MILPA")
    print("=" * 70)
    
    # 1. Verificar backend
    if not check_backend_health():
        print("\n⚠ El backend debe estar corriendo en http://localhost:8000")
        print("  Ejecuta: python -m uvicorn milpa_ai_backend.main:app --host 127.0.0.1 --port 8000")
        return False
    
    # 2. Verificar BD
    num_docs, num_fragments = check_database()
    
    # 3. Insertar datos de prueba si es necesario
    if num_fragments == 0:
        print("\n→ No hay fragmentos, insertando datos de prueba...")
        insert_test_data()
        num_docs, num_fragments = check_database()
    
    # 4. Reconstruir índices
    print()
    if not rebuild_indexes():
        return False
    
    # 5. Ejecutar consultas de prueba
    print("\n" + "=" * 70)
    print("PRUEBAS DE CONSULTA RAG")
    print("=" * 70)
    
    test_cases = [
        {
            "query": "¿Cómo fertilizar maíz con nitrógeno?",
            "keywords": ["nitrógeno", "maíz", "fertilización", "kg/ha"]
        },
        {
            "query": "¿Qué dosis de fósforo aplicar en siembra?",
            "keywords": ["fósforo", "P2O5", "siembra", "kg/ha"]
        },
        {
            "query": "Control de plagas en tomate",
            "keywords": ["tomate", "plagas", "Tuta"]
        }
    ]
    
    results = []
    for test in test_cases:
        success = test_rag_query(test["query"], test.get("keywords"))
        results.append(success)
    
    # 6. Resumen
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests pasados: {passed}/{total}")
    
    if passed == total:
        print("\n✓ El sistema RAG está OPERATIVO")
        print("\nCómo usar:")
        print("  1. Indexa tus documentos llamando a POST /api/index/rebuild")
        print("  2. Consulta con POST /api/query enviando:")
        print("     {\"query\": \"tu pregunta\", \"k\": 5, \"mode\": \"hybrid\"}")
        print("  3. Modos disponibles: hybrid (recomendado), dense, lex")
        return True
    else:
        print("\n✗ Algunos tests fallaron - revisa los logs arriba")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
