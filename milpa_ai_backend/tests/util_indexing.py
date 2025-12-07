# milpa_ai_backend/tests/util_indexing.py
# ------------------------------------------------------------
# Utilidades de indexación para pruebas:
#  - index_in_bm25(bm25_index, fragments): carga fragmentos en un índice BM25.
#  - index_in_vector_store(embedder, vector_store, fragments): inserta embeddings en Chroma.
#
# Este módulo provee EXACTAMENTE los símbolos que los tests importan:
#   from tests.util_indexing import index_in_bm25, index_in_vector_store
#
# Diseñado con "duck-typing": intenta adaptarse a pequeñas variaciones de API
# (p.ej., BM25Index.add vs BM25Index.add_documents; EmbeddingModel.encode vs embed).
# ------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

__all__ = ["index_in_bm25", "index_in_vector_store"]


def _iter_records_from_fragments(
    fragments: Iterable[Dict[str, Any]],
) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    """
    Convierte cada fragmento con estructura:
      {
        "fragment_id": str,
        "doc_id": str,
        "text_es": str,
        "labels": List[str],
        "entities": List[{"type":..., "value":..., ...}]
      }
    en tuplas (doc_id, text, metadata) listas para indexar.
    
    NOTA: ChromaDB no acepta listas como valores de metadatos, así que
    serializamos labels como string (separado por comas) y entities como JSON string.
    """
    import json
    
    for f in fragments:
        frag_id = f.get("fragment_id") or f.get("id")
        doc_id = f.get("doc_id") or "doc_unknown"
        text = f.get("text_es") or f.get("text") or ""
        labels = list(f.get("labels") or [])
        entities = list(f.get("entities") or [])

        # Metadata mínima y estable para trazabilidad en pruebas
        # ChromaDB requiere valores escalares (str, int, float, bool), no listas
        md = {
            "fragment_id": frag_id,
            "doc_id": doc_id,
            "labels": ",".join(labels),  # Lista → string separado por comas
            "entities": json.dumps(entities),  # Lista de dicts → JSON string
        }
        yield (f"{doc_id}::{frag_id}", text, md)


# ------------------------------------------------------------
# BM25
# ------------------------------------------------------------
def index_in_bm25(bm25_index: Any, fragments: Iterable[Dict[str, Any]]) -> List[str]:
    """
    Indexa los fragmentos en un índice BM25.
    Devuelve la lista de IDs (doc_ids internos del índice) que se insertaron.

    Soporta dos estilos de API:
      - bm25_index.add_documents(docs=[{"id":..., "text":..., "metadata":...}, ...])
      - bm25_index.add(doc_id: str, text: str, **kwargs)
    """
    inserted_ids: List[str] = []
    records = list(_iter_records_from_fragments(fragments))
    if not records:
        return inserted_ids

    # Intento 1: API por lote
    docs_payload = [
        {"id": rid, "text": text, "metadata": md} for (rid, text, md) in records
    ]
    if hasattr(bm25_index, "add_documents"):
        bm25_index.add_documents(docs_payload)
        inserted_ids = [d["id"] for d in docs_payload]
        return inserted_ids

    # Intento 2: API uno-a-uno
    if hasattr(bm25_index, "add"):
        for rid, text, md in records:
            # Algunas implementaciones aceptan (id, text) y otras (id, text, metadata=...)
            try:
                bm25_index.add(rid, text, metadata=md)  # type: ignore[call-arg]
            except TypeError:
                bm25_index.add(rid, text)  # type: ignore[call-arg]
            inserted_ids.append(rid)
        return inserted_ids

    # Intento 3: reset + rebuild si existe build() / index(docs)
    if hasattr(bm25_index, "index"):
        bm25_index.index(docs_payload)  # type: ignore[attr-defined]
        inserted_ids = [d["id"] for d in docs_payload]
        return inserted_ids

    # Si ninguna API coincide, falla claramente para facilitar el ajuste.
    raise AttributeError(
        "BM25Index no expone métodos compatibles. Se esperaba uno de: "
        "add_documents(docs), add(id, text[, metadata]), index(docs)"
    )


# ------------------------------------------------------------
# Vector Store (Chroma)
# ------------------------------------------------------------
def _embed_batch(embedder: Any, texts: List[str]) -> List[List[float]]:
    """
    Obtiene embeddings usando el método disponible en el modelo.
    Soporta:
      - embedder.encode(texts)
      - embedder.embed(texts)
      - embedder.embed_texts(texts)
    """
    if hasattr(embedder, "encode"):
        return embedder.encode(texts)  # type: ignore[attr-defined]
    if hasattr(embedder, "embed"):
        return embedder.embed(texts)  # type: ignore[attr-defined]
    if hasattr(embedder, "embed_texts"):
        return embedder.embed_texts(texts)  # type: ignore[attr-defined]
    raise AttributeError(
        "EmbeddingModel no expone encode/embed/embed_texts para obtener vectores."
    )


def index_in_vector_store(
    embedder: Any,
    vector_store: Any,
    fragments: Iterable[Dict[str, Any]],
    batch_size: int = 64,
) -> List[str]:
    """
    Inserta los fragmentos en el almacén vectorial (Chroma/Qdrant/pgvector wrapper).
    Devuelve la lista de IDs (rid: 'doc_id::fragment_id') insertados.

    Requisitos de API mínimos:
      - vector_store.add(ids: List[str], embeddings: List[List[float]], metadatas: List[dict])
      - embedder.encode|embed|embed_texts(List[str]) -> List[List[float]]
    """
    # Prepara registros
    recs = list(_iter_records_from_fragments(fragments))
    if not recs:
        return []

    ids_all: List[str] = []
    texts_all: List[str] = []
    metas_all: List[Dict[str, Any]] = []
    for rid, text, md in recs:
        ids_all.append(rid)
        texts_all.append(text)
        metas_all.append(md)

    inserted_ids: List[str] = []

    # Inserción por lotes para evitar picos de memoria
    for i in range(0, len(texts_all), batch_size):
        chunk_ids = ids_all[i : i + batch_size]
        chunk_texts = texts_all[i : i + batch_size]
        chunk_metas = metas_all[i : i + batch_size]

        embs = _embed_batch(embedder, chunk_texts)

        # Validaciones mínimas
        if len(embs) != len(chunk_ids):
            raise ValueError(
                f"Dimensión inconsistente: embeddings={len(embs)} ids={len(chunk_ids)}"
            )
        if not hasattr(vector_store, "add"):
            raise AttributeError(
                "VectorStore no expone método add(ids, embeddings, metadatas)."
            )

        # Inserta en el almacén vectorial
        vector_store.add(ids=chunk_ids, embeddings=embs, metadatas=chunk_metas)
        inserted_ids.extend(chunk_ids)

    return inserted_ids
