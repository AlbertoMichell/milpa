# milpa_ai_backend/tests/test_contract_api.py
# Tests de contrato: validación de esquemas JSON con AJV y snapshot testing.

import pytest
import json
import os
from pathlib import Path
from fastapi.testclient import TestClient

# Configurar BD de tests ANTES de importar app
test_db = Path(__file__).parent.parent / "data" / "test_contract.db"
os.environ["SQLITE_PATH"] = str(test_db)

from api.server import app

client = TestClient(app)

# ────────────────────────────────────────────────────────────────
# ESQUEMAS ESPERADOS (Contract JSON Schemas)
# ────────────────────────────────────────────────────────────────

HEALTH_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"}
    },
    "required": ["ok"],
    "additionalProperties": False
}

LIBRARY_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "nombre": {"type": "string"},
                    "autor": {"type": ["string", "null"]},
                    "año": {"type": ["integer", "null"]},
                    "tipo": {"type": "string"},
                    "país": {"type": ["string", "null"]},
                    "idioma": {"type": ["string", "null"]},
                    "extraido_de": {"type": ["string", "null"]}
                },
                "required": ["id", "nombre", "tipo"]
            }
        },
        "total": {"type": "integer"},
        "offset": {"type": "integer"},
        "limit": {"type": "integer"}
    },
    "required": ["items", "total", "offset", "limit"]
}

LIBRARY_DETAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string"},
        "nombre": {"type": "string"},
        "autor": {"type": ["string", "null"]},
        "año": {"type": ["integer", "null"]},
        "tipo": {"type": "string"},
        "classification": {"type": ["string", "null"]},
        "license": {"type": ["string", "null"]},
        "tables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string"},
                    "page": {"type": "integer"},
                    "headers": {"type": "array"},
                    "rows": {"type": "array"}
                },
                "required": ["table_id", "page"]
            }
        }
    },
    "required": ["doc_id", "nombre", "tipo", "tables"]
}

FACETS_SCHEMA = {
    "type": "object",
    "properties": {
        "authors": {
            "type": "array",
            "items": {"type": "string"}
        },
        "years": {
            "type": "array",
            "items": {"type": "integer"}
        }
    },
    "required": ["authors", "years"]
}


# ────────────────────────────────────────────────────────────────
# VALIDADOR DE ESQUEMAS (usando jsonschema de Python)
# ────────────────────────────────────────────────────────────────

from jsonschema import validate, ValidationError


def assert_schema(data: dict, schema: dict):
    """Valida que data cumpla con schema JSON Schema."""
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        pytest.fail(f"Schema validation failed: {e.message}")


# ────────────────────────────────────────────────────────────────
# TESTS DE CONTRATO
# ────────────────────────────────────────────────────────────────

def test_health_contract():
    """Valida que /health responde con el contrato esperado."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert_schema(data, HEALTH_SCHEMA)
    assert data["ok"] is True


def test_library_list_contract():
    """Valida que /library responde con lista de items según contrato."""
    response = client.get("/library")
    assert response.status_code == 200
    data = response.json()
    assert_schema(data, LIBRARY_LIST_SCHEMA)
    # Validaciones adicionales
    assert isinstance(data["items"], list)
    assert data["total"] >= 0
    assert data["offset"] >= 0
    assert data["limit"] > 0


def test_library_list_with_filters_contract():
    """Valida que /library con filtros cumple contrato."""
    response = client.get("/library?q=prueba&offset=0&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert_schema(data, LIBRARY_LIST_SCHEMA)


def test_library_facets_contract():
    """Valida que /library/facets cumple contrato."""
    response = client.get("/library/facets")
    
    # El endpoint puede no estar implementado aún (404 aceptable) o devolver 200
    if response.status_code == 404:
        pytest.skip("Endpoint /library/facets no implementado aún")
    
    assert response.status_code == 200
    data = response.json()
    assert_schema(data, FACETS_SCHEMA)
    assert isinstance(data["authors"], list)
    assert isinstance(data["years"], list)


def test_library_detail_contract():
    """Valida que /library/{doc_id} cumple contrato si hay documentos."""
    # Primero obtener lista para conseguir un doc_id válido
    list_resp = client.get("/library?limit=1")
    items = list_resp.json().get("items", [])
    
    if not items:
        pytest.skip("No hay documentos en la BD para probar detalle")
    
    doc_id = items[0]["id"]
    response = client.get(f"/library/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert_schema(data, LIBRARY_DETAIL_SCHEMA)


# ────────────────────────────────────────────────────────────────
# SNAPSHOT TESTING (guardar snapshots esperados)
# ────────────────────────────────────────────────────────────────

SNAPSHOTS_DIR = "tests/snapshots"

def save_snapshot(name: str, data: dict):
    """Guarda snapshot JSON para comparación futura."""
    import os
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    path = f"{SNAPSHOTS_DIR}/{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_snapshot(name: str) -> dict:
    """Carga snapshot JSON guardado."""
    path = f"{SNAPSHOTS_DIR}/{name}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_health_snapshot():
    """Compara respuesta actual con snapshot guardado."""
    response = client.get("/health")
    data = response.json()
    
    # Para crear el snapshot inicial, descomenta:
    # save_snapshot("health", data)
    
    # Comparar con snapshot
    try:
        expected = load_snapshot("health")
        assert data == expected, "Health response changed from snapshot"
    except FileNotFoundError:
        pytest.skip("Snapshot no existe aún. Ejecuta con save_snapshot descomentado primero.")
