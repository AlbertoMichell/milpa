# milpa_ai_backend/core/telemetry/__init__.py
# OpenTelemetry instrumentation para FastAPI backend.
# SPRINT 19: Trazas distribuidas con sampling 10%.

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
import os

# ────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE RECURSOS
# ────────────────────────────────────────────────────────────────

resource = Resource.create({
    SERVICE_NAME: "milpa-ai-backend",
    "service.version": "1.0.0",
    "deployment.environment": os.getenv("ENVIRONMENT", "development")
})


# ────────────────────────────────────────────────────────────────
# TRACER PROVIDER CON SAMPLING 10%
# ────────────────────────────────────────────────────────────────

# Sampling 10%: solo 1 de cada 10 trazas se captura completa
sampler = ParentBasedTraceIdRatio(0.10)

tracer_provider = TracerProvider(
    resource=resource,
    sampler=sampler
)

# Exportador: OTLP (para Jaeger/Tempo/OpenTelemetry Collector)
# Fallback a console si no hay OTLP_ENDPOINT configurado
otlp_endpoint = os.getenv("OTLP_ENDPOINT")

if otlp_endpoint:
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
else:
    # En desarrollo: exportar a consola
    console_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))

trace.set_tracer_provider(tracer_provider)

# Tracer global
tracer = trace.get_tracer(__name__)


# ────────────────────────────────────────────────────────────────
# INSTRUMENTACIÓN AUTOMÁTICA DE FASTAPI
# ────────────────────────────────────────────────────────────────

def instrument_fastapi(app):
    """
    Instrumenta aplicación FastAPI para capturar trazas automáticamente.
    Debe llamarse después de crear la app FastAPI.
    """
    FastAPIInstrumentor.instrument_app(app)


# ────────────────────────────────────────────────────────────────
# HELPERS PARA ENRIQUECER SPANS
# ────────────────────────────────────────────────────────────────

def add_rag_context_to_span(
    doc_id: str = None,
    fragment_ids: list[str] = None,
    taxonomy_version: str = None,
    query: str = None
):
    """
    Enriquece span actual con contexto de RAG.
    Útil para debugging y análisis de trazas.
    """
    span = trace.get_current_span()
    if not span:
        return
    
    if doc_id:
        span.set_attribute("milpa.doc_id", doc_id)
    
    if fragment_ids:
        span.set_attribute("milpa.fragment_ids", ",".join(fragment_ids))
        span.set_attribute("milpa.num_fragments", len(fragment_ids))
    
    if taxonomy_version:
        span.set_attribute("milpa.taxonomy_version", taxonomy_version)
    
    if query:
        # Truncar query para no exponer datos sensibles completos
        span.set_attribute("milpa.query_length", len(query))
        span.set_attribute("milpa.query_preview", query[:50])


def create_rag_span(name: str):
    """
    Crea un span personalizado para operaciones RAG.
    Uso:
        with create_rag_span("retrieval"):
            # código de retrieval
            pass
    """
    return tracer.start_as_current_span(name)
