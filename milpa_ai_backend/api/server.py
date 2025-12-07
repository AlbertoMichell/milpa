# milpa_ai_backend/api/server.py
# -----------------------------------------------------------------------------
# Fábrica de la app FastAPI para el backend de IA de MILPA.
# - CORS estricto (configurable por env/Settings).
# - /health para liveness.
# - /metrics (Prometheus) instrumentado ANTES del startup (evita RuntimeError).
# - Migraciones de BD (yoyo/DDL) en startup (idempotentes).
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Importamos Instrumentator aquí (no dentro de startup) para instrumentar
# justo al construir la app y evitar: "Cannot add middleware after an application has started"
try:
    from prometheus_fastapi_instrumentator import Instrumentator
except Exception:
    # Si en algún entorno no está instalado, no rompemos el arranque.
    Instrumentator = None  # type: ignore

from milpa_ai_backend.core.config import settings  # Importar desde core.config directamente (no desde core.config.__init__)
from milpa_ai_backend.core.logic.db import run_migrations

# SPRINT 19: OpenTelemetry instrumentation
try:
    from milpa_ai_backend.core.telemetry import instrument_fastapi
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    instrument_fastapi = None  # type: ignore

# Importamos el router al final del build_app para evitar ciclos.
# (lo haremos dentro de build_app)
# from api.endpoints import router as api_router

# Logger del módulo
logger = logging.getLogger("milpa_ai.server")


def _parse_allowed_origins() -> List[str]:
    """
    Lee ALLOWED_ORIGIN de settings/env y devuelve una lista de orígenes para CORS.
    - Si es "*" → permite todos (desarrollo).
    - Si viene lista separada por comas → la convierte en lista.
    - Si falta → fallback a "*".
    """
    # Preferimos settings si existe el atributo; si no, tomamos del entorno.
    raw = getattr(settings, "ALLOWED_ORIGIN", None) or os.environ.get("ALLOWED_ORIGIN", "*")
    raw = (raw or "").strip()
    if not raw or raw == "*":
        return ["*"]

    # Soportar lista separada por comas: "http://localhost:8080,https://dashboard.milpa"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["*"]


def build_app() -> FastAPI:
    """
    Crea y configura la aplicación FastAPI:
      - CORS: control de orígenes client-side (Dashboard MILPA).
      - /health: endpoint de liveness.
      - /metrics: expuesto e instrumentado ANTES del ciclo de vida.
      - Migraciones de BD: en startup (idempotentes).
      - Rutas de API: se cargan desde api.endpoints.
    """
    app = FastAPI(title="MILPA AI", version="1.0.0")

    # -------------------------------------------------------------------------
    # CORS: aplicamos al construir la app (antes del startup).
    # -------------------------------------------------------------------------
    allowed_origins = _parse_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        # En el MVP aceptamos todos los métodos/cabeceras; puedes restringir a:
        # allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"]
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS habilitado para orígenes: %s", allowed_origins)

    # -------------------------------------------------------------------------
    # HEALTH: endpoint simple para liveness/readiness checks.
    # -------------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"ok": True}

    # -------------------------------------------------------------------------
    # MÉTRICAS PROMETHEUS:
    # Importante: instrumentar aquí (app recién creada), NO en startup.
    # Si instrumentáramos en startup, Starlette bloquearía el add_middleware y
    # verías: "Cannot add middleware after an application has started".
    #
    # Además, usamos app.state.metrics_instrumented para evitar instrumentar dos veces
    # (p. ej., si por algún motivo se llamara build_app más de una vez).
    # -------------------------------------------------------------------------
    enable_metrics = (os.environ.get("ENABLE_METRICS", "true") or "true").lower() == "true"
    if enable_metrics and Instrumentator is not None:
        if not getattr(app.state, "metrics_instrumented", False):
            # Puedes ajustar opciones aquí:
            # - should_group_status_codes=True → agrupa 2xx, 4xx, 5xx
            # - excluded_handlers para no medir /health o /metrics si quisieras
            try:
                Instrumentator(
                    should_group_status_codes=True,
                    should_ignore_untemplated=True,  # reduce cardinalidad
                ).instrument(app).expose(
                    app,
                    endpoint="/metrics",
                    include_in_schema=False,  # que no aparezca en /docs
                )
                app.state.metrics_instrumented = True
                logger.info("Prometheus /metrics instrumentado (ENABLE_METRICS=true).")
            except Exception as e:  # falla silenciosa controlada
                logger.exception("No se pudo instrumentar Prometheus: %s", e)
        else:
            logger.debug("Prometheus ya estaba instrumentado; se omite duplicación.")
    else:
        logger.info("Prometheus deshabilitado (ENABLE_METRICS=%s) o paquete no disponible.", enable_metrics)

    # -------------------------------------------------------------------------
    # STARTUP: migraciones de base de datos (idempotentes).
    # Las migraciones se ejecutan en cada proceso (workers) pero deben ser idempotentes.
    # run_migrations() DEBE manejar 'up-to-date' sin fallar.
    # -------------------------------------------------------------------------
    @app.on_event("startup")
    def _on_startup():
        try:
            logger.info("Ejecutando migraciones de esquema...")
            run_migrations()
            logger.info("Migraciones completadas.")
        except Exception as e:
            # Si hay un error de migración, preferimos fallar el arranque para no dejar
            # el servicio en un estado inconsistente.
            logger.exception("Error aplicando migraciones: %s", e)
            raise

    # -------------------------------------------------------------------------
    # RUTAS DEL API
    # Importamos aquí para evitar ciclos (api.endpoints puede importar partes de core/*)
    # -------------------------------------------------------------------------
    from milpa_ai_backend.api.endpoints import router as api_router  # import tardío
    app.include_router(api_router)
    
    # RAG router (SPRINT 17-20)
    try:
        from milpa_ai_backend.api.rag import router as rag_router
        app.include_router(rag_router)
        logger.info("RAG endpoints habilitados (/api/query, /api/index/rebuild)")
    except Exception as e:
        logger.warning(f"No se pudieron cargar endpoints RAG: {e}")
    
    # -------------------------------------------------------------------------
    # SPRINT 19: OpenTelemetry instrumentation
    # Instrumentar después de configurar rutas y middleware
    # -------------------------------------------------------------------------
    enable_otel = (os.environ.get("ENABLE_OTEL", "true") or "true").lower() == "true"
    if enable_otel and OTEL_AVAILABLE and instrument_fastapi is not None:
        try:
            instrument_fastapi(app)
            logger.info("OpenTelemetry instrumentado (ENABLE_OTEL=true, sampling 10%).")
        except Exception as e:
            logger.exception("No se pudo instrumentar OpenTelemetry: %s", e)
    else:
        logger.info("OpenTelemetry deshabilitado (ENABLE_OTEL=%s) o paquete no disponible.", enable_otel)

    return app


# -------------------------------------------------------------------------
# INSTANCIA GLOBAL: para tests y ejecución con uvicorn
# -------------------------------------------------------------------------
app = build_app()
