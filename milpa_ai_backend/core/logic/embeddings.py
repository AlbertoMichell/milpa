# milpa_ai_backend/core/logic/embeddings.py
# ------------------------------------------------------------
# Gestión de embeddings:
# - Carga de modelo Sentence-Transformers (HF) con versión pinneada.
# - Fallback "dummy" determinista si no hay ST o falla la carga
#   (útil para entornos mínimos y ejecución de tests de integración).
# - Embed de listas y consultas con cache ligera.
# - Exposición de metadatos: model_name, model_sha, vector_dim.
# - Opción ONNX (no operativa aquí; hook de extensión listo).
# ------------------------------------------------------------
from __future__ import annotations
from typing import List, Dict, Optional
import hashlib
import os
import math
import warnings
from functools import lru_cache

# Config (opcional)
try:
    from core.config import settings
except Exception:
    class _S:
        # Elegido por calidad/latencia y cobertura multilingüe.
        EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    settings = _S()

# sentence-transformers opcional
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:
    SentenceTransformer = None  # type: ignore

# ONNX opcional (no se configura por defecto)
try:
    import onnxruntime as ort  # type: ignore
except Exception:
    ort = None  # type: ignore


class EmbeddingModel:
    """
    Wrapper de embeddings con:
      - backend=ST por defecto (si está instalado y el modelo carga),
      - backend=dummy si no hay ST, falla la carga o se fuerza por ENV.

    Variables de entorno soportadas:
      EMBEDDING_MODEL   -> nombre/ruta del modelo ST (prioridad sobre settings)
      EMBEDDINGS_DUMMY  -> "1"/"true" para forzar dummy
      EMBEDDINGS_DIM    -> dimensión a usar en dummy (por defecto 384)
    """

    def __init__(self, model_name: Optional[str] = None, use_onnx: bool = False):
        # Config efectivas
        self.model_name = (
            model_name
            or os.environ.get("EMBEDDING_MODEL")
            or getattr(settings, "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        )
        self.use_onnx = use_onnx and (ort is not None)
        self._model = None  # instancia ST si aplica
        self._backend = "dummy"  # "st" | "dummy"
        self._vector_dim: Optional[int] = None

        # ¿se fuerza dummy?
        force_dummy = str(os.environ.get("EMBEDDINGS_DUMMY", "")).lower() in ("1", "true", "yes")

        if not force_dummy and not self.use_onnx:
            # Intentar cargar Sentence-Transformers
            if SentenceTransformer is not None:
                try:
                    self._model = SentenceTransformer(self.model_name)
                    # Intentar leer la dimensión sin inferencia
                    get_dim = getattr(self._model, "get_sentence_embedding_dimension", None)
                    if callable(get_dim):
                        self._vector_dim = int(get_dim())
                    else:
                        # fallback: inferir con un sample
                        v = self._model.encode(["hola"], convert_to_numpy=True, normalize_embeddings=True)[0]
                        self._vector_dim = int(v.shape[0])
                    self._backend = "st"
                except Exception as e:
                    warnings.warn(
                        f"[EmbeddingModel] No se pudo cargar '{self.model_name}' "
                        f"({type(e).__name__}: {e}). Se usará backend 'dummy'."
                    )
                    self._init_dummy()
            else:
                warnings.warn("[EmbeddingModel] sentence-transformers no está instalado. Se usará backend 'dummy'.")
                self._init_dummy()
        elif self.use_onnx:
            # Hook ONNX (no implementado en este MVP)
            warnings.warn("[EmbeddingModel] ONNX habilitado pero no implementado. Se usará backend 'dummy'.")
            self._init_dummy()
        else:
            # Forzado por ENV
            self._init_dummy()

    # ------------------------ Inicialización dummy ------------------------

    def _init_dummy(self) -> None:
        """
        Inicializa el modo dummy:
          - Dimensión configurable por ENV EMBEDDINGS_DIM (default=384).
          - Genera vectores deterministas a partir de SHA1(texto|i).
          - Los vectores se normalizan L2.
        """
        self._backend = "dummy"
        try:
            dim = int(os.environ.get("EMBEDDINGS_DIM", "384"))
            if dim <= 0:
                raise ValueError
        except Exception:
            dim = 384
        self._vector_dim = dim
        # No se requiere modelo.

    # -------------------------- Propiedades --------------------------

    @property
    def vector_dim(self) -> int:
        # Siempre retornamos una dimensión válida.
        if self._vector_dim is None:
            # fallback conservador
            return 384
        return self._vector_dim

    @property
    def model_sha(self) -> str:
        """
        SHA estable a partir del nombre del modelo y backend.
        En 'dummy' incluye la dimensión para distinguir variantes.
        """
        tag = f"{self.model_name}@{self._backend}@{self.vector_dim}"
        return hashlib.sha1(tag.encode("utf-8")).hexdigest()

    @property
    def is_dummy(self) -> bool:
        return self._backend == "dummy"

    # --------------------------- Embeddings ---------------------------

    @lru_cache(maxsize=4096)
    def _embed_one_cached(self, text: str) -> List[float]:
        """
        Embedding de un solo texto con cache LRU (para queries repetidas).
        """
        if self._backend == "st":
            # encode retorna np.ndarray; convertimos a list[float]
            emb = self._model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
            # Convertimos a float32 list para ahorrar memoria.
            return emb.astype("float32").tolist()
        # dummy
        return self._dummy_embed(text, self.vector_dim)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Embedding de lista de textos:
          - ST: usa batch encode para eficiencia.
          - dummy: genera por cada entrada (determinista).
        """
        if self._backend == "st":
            # Batch encode para eficiencia y normalización
            embs = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            # A float32 list
            return [e.astype("float32").tolist() for e in embs]
        # dummy
        return [self._dummy_embed(t, self.vector_dim) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        """
        Embedding para una sola consulta (aplica cache).
        """
        return self._embed_one_cached(text)

    # --------------------------- Dummy core ---------------------------

    @staticmethod
    def _dummy_embed(text: str, dim: int) -> List[float]:
        """
        Genera un vector determinista en R^dim a partir de SHA1(text|i).
        - Distribución pseudo-aleatoria reproducible por posición.
        - Normalización L2 para que coseno funcione razonablemente.
        """
        # Construimos valores deterministas en [-0.5, 0.5]
        vals = []
        for i in range(dim):
            h = hashlib.sha1(f"{text}|{i}".encode("utf-8")).digest()
            # Tomamos 4 bytes -> entero -> map a [0,1), desplazar a [-0.5, 0.5]
            n = int.from_bytes(h[:4], byteorder="big", signed=False)
            v = (n / 2**32) - 0.5
            vals.append(v)

        # Normalización L2
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        vals = [float(v / norm) for v in vals]
        return vals
