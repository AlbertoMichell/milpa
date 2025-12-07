# milpa_ai_backend/core/config.py
# Config centralizada con pydantic-settings (Pydantic v2).
# Incluye límites de upload, origen CORS permitido y parámetros iniciales.
from pydantic_settings import BaseSettings
from pydantic import Field
import hashlib, json

class Settings(BaseSettings):
    # Rutas y almacenamiento
    DATA_DIR: str = Field(default="data/documents", description="Directorio de documentos originales")
    SQLITE_PATH: str = Field(default="data/milpa_knowledge.db", description="Ruta a la base SQLite")
    CHROMA_DIR: str = Field(default="data/vector_db", description="Directorio para índices vectoriales")

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        # Permitir que variables de entorno sobrescriban defaults
        case_sensitive = True

    # Seguridad / CORS
    ALLOWED_ORIGIN: str = Field(default="https://dashboard.milpa", description="Origen permitido para CORS")

    # Uploads
    MAX_UPLOAD_MB: int = Field(default=25, description="Límite máximo de upload en MB")

    # AV (ClamAV)
    CLAMAV_HOST: str = Field(default="clamav", description="Host del daemon clamd")
    CLAMAV_PORT: int = Field(default=3310, description="Puerto del daemon clamd")
    AV_OPTIONAL: bool = Field(default=False, description="Permitir continuar si AV no disponible")

    # Config de RAG (placeholders de SPRINTs posteriores)
    EMBEDDING_MODEL: str = Field(default="paraphrase-multilingual-MiniLM-L12-v2")
    EMBEDDING_MODEL_SHA: str = Field(default="")
    RERANKER_MODEL: str = Field(default="bge-reranker-base")
    RERANKER_VERSION: str = Field(default="1.0.0")
    RAG_MODE: str = Field(default="hybrid")
    BM25_TOPK: int = Field(default=100)
    K_RETRIEVE: int = Field(default=8)
    RRF_K: int = Field(default=60)
    CHUNK_SIZE: int = Field(default=1000)
    CHUNK_OVERLAP: float = Field(default=0.2)
    OCR_MAX_PAGES: int = Field(default=300)
    TAXONOMY_VERSION: str = Field(default="2025.09.10")
    GLOSSARY_VERSION: str = Field(default="2025.09.10")
    TM_VERSION: str = Field(default="2025.09.10")

    # JWT (para validación futura en endpoints)
    JWT_PUBLIC_KEY: str = Field(default="")

    # DPIA / cumplimiento
    DPIA_ID: str = Field(default="dpia-2025-01")

    @property
    def MAX_UPLOAD_BYTES(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

settings = Settings()

def config_fingerprint() -> str:
    """
    Huella de configuración (sin llaves/secretos) para trazabilidad en runs.
    """
    s = settings.model_dump()
    s.pop("JWT_PUBLIC_KEY", None)
    return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()
