# milpa_ai_backend/core/logic/vectordb.py
# ------------------------------------------------------------
# Capa de almacenamiento vectorial (ChromaDB persistente).
# - Colección persistente con espacio cosine (por defecto en Chroma).
# - add / upsert y query con filtros de metadatos.
# - Acepta 'path' explícito para compatibilidad con tests/fixtures.
#
# NOTA IMPORTANTE (compatibilidad):
# En algunas versiones de Chroma con backend Rust, pasar metadatos HNSW
# (p. ej. {"hnsw:M": 32, ...}) provoca:
#   chromadb.errors.InvalidArgumentError: Failed to parse hnsw parameters...
# Por lo tanto, aquí NO enviamos metadatos HNSW; dejamos los defaults.
# Si ya existe una colección creada con metadatos inválidos, borra el
# directorio de persistencia antes de re-crear para evitar reaperturas
# incompatibles.
# ------------------------------------------------------------
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os

# Config opcional (para rutas por defecto)
try:
    from core.config import settings
except Exception:  # pragma: no cover - fallback cuando no existe settings
    class _S:
        CHROMA_DIR = "data/vector_db"
    settings = _S()

# Chroma opcional
try:
    import chromadb  # noqa: F401
    from chromadb import PersistentClient
except Exception:  # pragma: no cover - permite que los tests salten si no hay Chroma
    chromadb = None
    PersistentClient = None


class VectorStore:
    """
    Pequeña envoltura de Chroma persistente.

    Args:
        path: ruta de persistencia; si no se indica, usa settings.CHROMA_DIR.
        collection: nombre de la colección.

    Métodos:
        add(ids, embeddings, metadatas)
        upsert(ids, embeddings, metadatas)
        query(query_emb, k=8, where=None) -> List[{fragment_id, score, metadata}]
    """

    def __init__(self, path: Optional[str] = None, collection: str = "milpa"):
        if PersistentClient is None:
            raise RuntimeError(
                "Chroma no está instalado. Instálalo (chromadb>=1.x) para usar VectorStore."
            )

        self.path = path or getattr(settings, "CHROMA_DIR", "data/vector_db")
        os.makedirs(self.path, exist_ok=True)

        # Cliente persistente
        self.client = PersistentClient(path=self.path)

        # Crea/obtiene colección SIN metadatos HNSW (evita errores en backend Rust).
        # El espacio por defecto es 'cosine' cuando se usan embeddings normalizados,
        # y Chroma se encarga de los parámetros internos del índice.
        self.col = self.client.get_or_create_collection(
            name=collection
            # NO pasar 'metadata={...}' aquí para evitar InvalidArgumentError.
        )

    # ---------------------- Escritura ----------------------

    def reset(self) -> None:
        """
        Elimina todos los documentos de la colección.
        Útil para reconstruir índices desde cero.
        """
        # Obtener todos los IDs
        result = self.col.get()
        if result and result.get("ids"):
            ids = result["ids"]
            if ids:
                self.col.delete(ids=ids)
    
    def add(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """
        Inserta nuevos vectores (IDs deben ser únicos).
        Se recomienda que cada metadata incluya al menos:
          { "fragment_id": <igual a id>, "doc_id": str, "labels": [..], "entities": [{type,value}] }
        """
        # Chroma espera len(ids) == len(embeddings) == len(metadatas)
        self.col.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    def upsert(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """
        Upsert básico (delete+add) si la versión de Chroma no expone upsert nativo.
        En versiones recientes, .upsert existe y conviene usarlo.
        """
        try:
            upsert_fn = getattr(self.col, "upsert", None)
            if callable(upsert_fn):
                upsert_fn(ids=ids, embeddings=embeddings, metadatas=metadatas)
                return
        except Exception:
            # Si falla, caemos al fallback por compatibilidad.
            pass

        # Fallback estable
        try:
            self.col.delete(ids=ids)
        except Exception:
            # Si no existían previamente, ignoramos el error.
            pass
        self.col.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    # ----------------------- Lectura -----------------------

    def query(
        self,
        query_emb: List[float],
        k: int = 8,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Realiza búsqueda vectorial.

        Args:
            query_emb: embedding de la consulta.
            k: número de resultados.
            where: filtro de metadatos, p.ej.
                   {"labels": {"$in": ["RECOMENDACION"]}, "doc_id": "doc123"}

        Returns:
            Lista de dicts con: fragment_id, score (≈1 - distancia_cosine), metadata.
        """
        # ChromaDB no acepta where={}, así que solo lo incluimos si tiene contenido
        # ChromaDB siempre devuelve ids, no hace falta incluirlo en "include"
        query_params = {
            "query_embeddings": [query_emb],
            "n_results": k,
            "include": ["metadatas", "distances"],
        }
        if where:
            query_params["where"] = where
        
        res = self.col.query(**query_params)

        # Estructura esperada: {"ids":[[...]], "distances":[[...]], "metadatas":[[{...},...]]}
        # Los IDs siempre se devuelven automáticamente
        ids = res.get("ids", [[]])[0] or []
        dists = res.get("distances", [[]])[0] or []
        metas = res.get("metadatas", [[]])[0] or []

        out: List[Dict[str, Any]] = []
        for i, fid in enumerate(ids):
            dist = float(dists[i]) if i < len(dists) else 1.0
            # Chroma devuelve distancia de coseno en [0..2] según versión/config;
            # para similitud aproximada usamos 1 - dist asumiendo normalización.
            score = max(0.0, 1.0 - dist)
            meta = metas[i] if i < len(metas) else {}
            out.append(
                {
                    "fragment_id": fid,
                    "score": score,
                    "metadata": meta,
                }
            )
        return out
