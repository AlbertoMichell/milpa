#!/usr/bin/env python3
"""
Script de verificación completa del sistema MILPA AI.
Prueba todos los endpoints y funcionalidades.
"""

import requests
import json
import time
from typing import Dict, Any

API_BASE = "http://localhost:8000"
RESULTS = []

def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_success(text: str):
    print(f"✅ {text}")
    RESULTS.append(("✅", text))

def print_error(text: str):
    print(f"❌ {text}")
    RESULTS.append(("❌", text))

def print_info(text: str):
    print(f"ℹ️  {text}")

def test_health():
    """Test 1: Health check"""
    print_header("TEST 1: Health Check")
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            print_success("Servidor respondiendo correctamente")
            print_info(f"Response: {response.json()}")
            return True
        else:
            print_error(f"Health check falló: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"No se pudo conectar al servidor: {e}")
        return False

def test_feature_flags():
    """Test 2: Feature flags"""
    print_header("TEST 2: Feature Flags")
    try:
        response = requests.get(f"{API_BASE}/admin/feature-flags")
        if response.status_code == 200:
            flags = response.json()["flags"]
            print_success(f"Feature flags cargados: {len(flags)} flags")
            
            enabled = [f for f in flags if f["enabled"]]
            print_info(f"Flags activos: {len(enabled)}/{len(flags)}")
            
            for flag in flags[:3]:
                print_info(f"  - {flag['flag_name']}: {'ON' if flag['enabled'] else 'OFF'}")
            
            return True
        else:
            print_error(f"Error cargando feature flags: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False

def test_library():
    """Test 3: Biblioteca de documentos"""
    print_header("TEST 3: Biblioteca de Documentos")
    try:
        response = requests.get(f"{API_BASE}/library")
        if response.status_code == 200:
            data = response.json()
            print_success(f"Biblioteca accesible: {data['total']} documentos")
            
            if data["items"]:
                doc = data["items"][0]
                print_info(f"Ejemplo: {doc['nombre']} ({doc['tipo']})")
            
            return True
        else:
            print_error(f"Error cargando biblioteca: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False

def test_rag_query():
    """Test 4: Consulta RAG"""
    print_header("TEST 4: Consulta RAG (Query)")
    queries = [
        "¿Cuáles son los nutrientes esenciales del maíz?",
        "¿Qué plagas afectan al tomate?",
        "Fertilización de frijol"
    ]
    
    success_count = 0
    
    for query in queries:
        print_info(f"Query: {query}")
        try:
            payload = {
                "query": query,
                "k": 5,
                "mode": "hybrid"
            }
            
            response = requests.post(
                f"{API_BASE}/api/query",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                fragments = data.get("total_retrieved", 0)
                answer_mode = data.get("answer_mode", "N/A")
                
                print_success(f"  → {fragments} fragmentos | Modo: {answer_mode}")
                
                if data.get("answer"):
                    print_info(f"  Respuesta: {data['answer'][:100]}...")
                
                success_count += 1
            else:
                print_error(f"  Query falló: {response.status_code}")
        
        except Exception as e:
            print_error(f"  Excepción: {e}")
        
        time.sleep(0.5)
    
    if success_count == len(queries):
        print_success(f"Todas las queries exitosas ({success_count}/{len(queries)})")
        return True
    else:
        print_error(f"Algunas queries fallaron ({success_count}/{len(queries)})")
        return False

def test_index_stats():
    """Test 5: Estadísticas de índices"""
    print_header("TEST 5: Estadísticas del Sistema")
    try:
        # Obtener stats de biblioteca
        lib_response = requests.get(f"{API_BASE}/library")
        if lib_response.status_code != 200:
            print_error("No se pudieron obtener estadísticas")
            return False
        
        lib_data = lib_response.json()
        
        # Obtener feature flags
        flags_response = requests.get(f"{API_BASE}/admin/feature-flags")
        if flags_response.status_code != 200:
            print_error("No se pudieron obtener feature flags")
            return False
        
        flags_data = flags_response.json()
        
        # Mostrar estadísticas
        print_success("Estadísticas del sistema:")
        print_info(f"  📚 Documentos: {lib_data['total']}")
        print_info(f"  📄 Fragmentos estimados: {lib_data['total'] * 4}")
        print_info(f"  🚩 Feature flags: {len([f for f in flags_data['flags'] if f['enabled']])}/{len(flags_data['flags'])} activos")
        print_info(f"  🔍 RAG Mode: hybrid")
        print_info(f"  📊 Embeddings: paraphrase-multilingual-MiniLM-L12-v2")
        
        return True
    
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False

def test_admin_interface():
    """Test 6: Interfaz de administración"""
    print_header("TEST 6: Interfaz Web de Administración")
    try:
        response = requests.get(f"{API_BASE}/admin", timeout=5)
        if response.status_code == 200:
            html_size = len(response.text)
            print_success(f"Interfaz web accesible ({html_size} bytes)")
            print_info(f"URL: {API_BASE}/admin")
            return True
        else:
            print_error(f"Interfaz no accesible: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False

def print_summary():
    """Resumen final"""
    print_header("RESUMEN DE PRUEBAS")
    
    success = sum(1 for r in RESULTS if r[0] == "✅")
    total = len(RESULTS)
    
    print(f"\nResultados: {success}/{total} pruebas exitosas\n")
    
    for icon, msg in RESULTS:
        print(f"{icon} {msg}")
    
    print(f"\n{'='*60}\n")
    
    if success == total:
        print("🎉 ¡SISTEMA 100% OPERATIVO!")
        print("✅ Todos los componentes funcionando correctamente")
        print(f"🌐 Interfaz: {API_BASE}/admin")
        print(f"📚 Biblioteca: {API_BASE}/library")
        print(f"🔍 RAG Query: POST {API_BASE}/api/query")
    else:
        print(f"⚠️  Algunas pruebas fallaron ({total - success} errores)")
        print("Revisa los logs para más detalles")
    
    print(f"\n{'='*60}\n")

def main():
    print("\n" + "="*60)
    print("  🌾 MILPA AI - Verificación Completa del Sistema")
    print("="*60)
    print(f"\nServidor: {API_BASE}")
    print("Ejecutando pruebas...\n")
    
    tests = [
        test_health,
        test_feature_flags,
        test_library,
        test_rag_query,
        test_index_stats,
        test_admin_interface
    ]
    
    for test in tests:
        test()
        time.sleep(0.5)
    
    print_summary()

if __name__ == "__main__":
    main()
