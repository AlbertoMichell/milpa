# milpa_ai_backend/tests/test_embeddings_vectordb.py
# ------------------------------------------------------------
# Pruebas de embeddings y consulta densa con Chroma.
# Se salta si chromadb o sentence-transformers no están instalados.
# ------------------------------------------------------------
import pytest
from tests.util_indexing import index_in_vector_store

chromadb = pytest.importorskip("chromadb")

def test_embedder_and_vector_store(embedder, vector_store, sample_fragments):
    # Embedder básico
    v = embedder.embed_texts(["hola", "agronomía"])
    assert len(v) == 2 and len(v[0]) == embedder.vector_dim

    # Indexar 10 fragments (orden correcto: embedder, vector_store, fragments)
    index_in_vector_store(embedder, vector_store, sample_fragments)

    # Consulta de prueba (maiz + N + macollaje)
    q = "fertilización con N en maiz durante macollaje"
    q_emb = embedder.embed_query(q)
    # Consulta sin filtro where para validar la recuperación básica
    # (los filtros complejos se validan en tests de integración)
    hits = vector_store.query(query_emb=q_emb, k=5)
    assert len(hits) > 0

    # Los metadatos deben incluir doc_id/labels/entities (ahora serializados como strings)
    top = hits[0]
    meta = top["metadata"]
    assert "doc_id" in meta and "labels" in meta and "entities" in meta
    
    # Validar que labels existe y es string. Algunos fragmentos pueden no tener labels (labels=[])
    # lo cual es válido en escenarios reales (fragmentos sin clasificación temática)
    assert isinstance(meta["labels"], str)
    
    # Validar que AL MENOS uno de los hits tiene labels no vacíos
    hits_with_labels = [h for h in hits if len(h["metadata"]["labels"]) > 0]
    assert len(hits_with_labels) > 0, "Debe haber al menos un fragmento con labels en los resultados"
