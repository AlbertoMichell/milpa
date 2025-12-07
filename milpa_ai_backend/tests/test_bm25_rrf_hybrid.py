# milpa_ai_backend/tests/test_bm25_rrf_hybrid.py
# ------------------------------------------------------------
# Pruebas de BM25, RRF e "insuficiente evidencia" con el HybridRetriever.
# Si chroma no está, se prueban rutas BM25; hybrid se salta.
# ------------------------------------------------------------
import pytest
from tests.util_indexing import index_in_bm25, index_in_vector_store

from core.logic.bm25 import BM25Index
from core.logic.rag_engine import HybridRetriever, insufficient_evidence, build_insufficient_response

def test_bm25_index_and_search(bm25_index, sample_fragments):
    index_in_bm25(bm25_index, sample_fragments)
    # Sin filtro de labels para simplificar el test básico
    hits = bm25_index.search("fertilización N maiz macollaje", topk=50)
    assert isinstance(hits, list)
    assert len(hits) >= 1
    assert "fragment_id" in hits[0] and "metadata" in hits[0]

@pytest.mark.skipif(pytest.importorskip("chromadb") is None, reason="Chroma no disponible")
def test_hybrid_rrf_and_thresholds(embedder, vector_store, bm25_index, sample_fragments):
    # Indexar en ambos motores (orden correcto: embedder, vector_store, fragments)
    index_in_bm25(bm25_index, sample_fragments)
    index_in_vector_store(embedder, vector_store, sample_fragments)

    retriever = HybridRetriever(vector_store=vector_store, bm25_index=bm25_index, embedder=embedder)

    # Consulta buena (espera evidencia suficiente) - sin filtros por ahora
    q = "fertilización con N en maiz durante macollaje"
    hits = retriever.hybrid(q, final_k=8)
    assert len(hits) >= 1

    is_insuf, diag, hits_filtered = insufficient_evidence(q, hits)
    assert is_insuf is False, f"No debería ser insuficiente: {diag}"

    # Consulta irrelevante (debería caer en insuficiencia)
    bad_q = "oxidación anódica en baterías de litio"
    hits2 = retriever.hybrid(bad_q, final_k=8)
    is_insuf2, diag2, hits_filtered2 = insufficient_evidence(bad_q, hits2)
    assert is_insuf2 is True
    resp = build_insufficient_response(bad_q, diag2)
    assert "insuficiente evidencia" in resp["respuesta_html"].lower()
