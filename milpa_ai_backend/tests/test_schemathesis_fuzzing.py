# Schemathesis configuration for fuzzing OpenAPI endpoints
# Ejecuta fuzzing automático contra las especificaciones OpenAPI de los servicios

import schemathesis
from hypothesis import settings

# ────────────────────────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ────────────────────────────────────────────────────────────────

# AI Backend OpenAPI
ai_schema = schemathesis.from_uri("http://localhost:8000/openapi.json")

# Presenter OpenAPI (si tiene especificación)
# presenter_schema = schemathesis.from_uri("http://localhost:3000/openapi.json")


# ────────────────────────────────────────────────────────────────
# HOOKS Y FILTROS
# ────────────────────────────────────────────────────────────────

@ai_schema.hooks.apply("before_generate_case")
def before_case(context, case):
    """Hook ejecutado antes de generar cada caso de test."""
    # Filtrar endpoints que requieren autenticación si aún no está implementada
    pass


@ai_schema.hooks.apply("after_call")
def after_call(context, case, response):
    """Hook ejecutado después de cada llamada API."""
    # Validaciones custom: ej. verificar headers de seguridad
    assert "X-Content-Type-Options" in response.headers or response.status_code >= 400, \
        "Missing security header X-Content-Type-Options"


# ────────────────────────────────────────────────────────────────
# TEST CASES GENERADOS AUTOMÁTICAMENTE
# ────────────────────────────────────────────────────────────────

@ai_schema.parametrize()
@settings(max_examples=50, deadline=5000)  # 50 ejemplos por endpoint, timeout 5s
def test_ai_backend_fuzzing(case):
    """
    Fuzzing automático de todos los endpoints del AI backend.
    Schemathesis genera casos válidos e inválidos según OpenAPI spec.
    """
    response = case.call()
    
    # Validaciones básicas
    case.validate_response(response)
    
    # Validaciones adicionales de negocio
    if response.status_code == 200:
        # Toda respuesta exitosa debe ser JSON válido
        assert response.headers.get("Content-Type", "").startswith("application/json"), \
            "200 response must be JSON"
        
        # Validar que el JSON parse correctamente
        try:
            data = response.json()
        except Exception as e:
            raise AssertionError(f"Invalid JSON in 200 response: {e}")


# ────────────────────────────────────────────────────────────────
# TESTS ESPECÍFICOS DE SEGURIDAD
# ────────────────────────────────────────────────────────────────

@ai_schema.parametrize(endpoint="/library")
@settings(max_examples=20)
def test_library_sql_injection_resistance(case):
    """
    Test específico para SQL injection en endpoint /library.
    Schemathesis intentará inyectar payloads maliciosos.
    """
    response = case.call()
    
    # No debe haber errores de SQL expuestos
    if response.status_code >= 500:
        body = response.text.lower()
        sql_errors = ["sql", "sqlite", "syntax error", "database"]
        for err in sql_errors:
            assert err not in body, f"SQL error exposed in response: {body[:200]}"


@ai_schema.parametrize()
@settings(max_examples=10)
def test_no_sensitive_data_leak(case):
    """
    Verifica que respuestas de error no filtren información sensible.
    """
    response = case.call()
    
    if response.status_code >= 400:
        body = response.text.lower()
        sensitive_patterns = [
            "/home/", "/root/", "c:\\", "password", "secret", "api_key",
            "traceback", "exception", "stack trace"
        ]
        
        for pattern in sensitive_patterns:
            assert pattern not in body, \
                f"Sensitive data '{pattern}' leaked in error response"


# ────────────────────────────────────────────────────────────────
# EJECUTAR DESDE CLI
# ────────────────────────────────────────────────────────────────

# Para ejecutar Schemathesis desde línea de comandos en CI:
# 
# schemathesis run http://localhost:8000/openapi.json \
#   --checks all \
#   --max-examples=100 \
#   --hypothesis-deadline=5000 \
#   --exitfirst
#
# O con Docker:
# docker run schemathesis/schemathesis:stable run http://host.docker.internal:8000/openapi.json
