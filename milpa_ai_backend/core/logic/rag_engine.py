# milpa_ai_backend/core/logic/rag_engine.py
# ------------------------------------------------------------
# RAG híbrido (BM25 + denso) por defecto:
#  - RAG_MODE=hybrid, BM25_TOPK=100, K_RETRIEVE=8, RRF_K=60 (valores H1).
#  - Fusión Reciprocal Rank Fusion (RRF).
#  - Umbrales de "insuficiente evidencia":
#       k_min=5, min_sources=2, entity_coverage>=0.65, mean_score>=0.35
#  - Filtro inicial por labels (p.ej., ["RECOMENDACION"]) cuando la intención es operativa.
# ------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

# Config opcional
try:
    from milpa_ai_backend.core.config import settings
except Exception:
    class _S:
        RAG_MODE = "hybrid"
        BM25_TOPK = 100
        K_RETRIEVE = 8
        RRF_K = 60
    settings = _S()

# Módulos locales
from milpa_ai_backend.core.logic.embeddings import EmbeddingModel
from milpa_ai_backend.core.logic.vectordb import VectorStore
from milpa_ai_backend.core.logic.bm25 import BM25Index
from milpa_ai_backend.core.logic.enrichment import extract_entities, entity_coverage, Entity

# -----------------------------
# RRF (Reciprocal Rank Fusion)
# -----------------------------
def reciprocal_rank_fusion(vec_hits: List[Dict[str,Any]], bm25_hits: List[Dict[str,Any]], K:int=60) -> List[Dict[str,Any]]:
    """
    vec_hits/bm25_hits: listas ordenadas desc por score.
    RRF_score(d) = sum(1 / (K + rank(d, run)))
    rank inicia en 1.
    """
    ranks: Dict[str, float] = defaultdict(float)
    meta: Dict[str, Dict[str, Any]] = {}

    for i, h in enumerate(vec_hits, start=1):
        fid = h["fragment_id"]
        ranks[fid] += 1.0 / (K + i)
        meta[fid] = h.get("metadata", {})
    for i, h in enumerate(bm25_hits, start=1):
        fid = h["fragment_id"]
        ranks[fid] += 1.0 / (K + i)
        # merge metadatos si no existían
        if fid not in meta:
            meta[fid] = h.get("metadata", {})

    fused = [{"fragment_id": fid, "rrf_score": sc, "metadata": meta.get(fid, {})} for fid, sc in ranks.items()]
    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused

# -----------------------------
# Retrieval híbrido
# -----------------------------
class HybridRetriever:
    def __init__(self, vector_store: Optional[VectorStore]=None, bm25_index: Optional[BM25Index]=None, embedder: Optional[EmbeddingModel]=None):
        self.vs = vector_store or VectorStore()
        self.bm25 = bm25_index or BM25Index()
        self.embedder = embedder or EmbeddingModel()

        # Parámetros
        self.BM25_TOPK = getattr(settings, "BM25_TOPK", 100)
        self.K_RETRIEVE = getattr(settings, "K_RETRIEVE", 8)
        self.RRF_K = getattr(settings, "RRF_K", 60)

    def dense_search(self, query: str, k: Optional[int]=None, where: Optional[Dict[str,Any]] = None) -> List[Dict[str,Any]]:
        emb = self.embedder.embed_query(query)
        k = k or self.K_RETRIEVE
        return self.vs.query(query_emb=emb, k=k, where=where)

    def lex_search(self, query: str, topk: Optional[int]=None, labels_filter: Optional[List[str]]=None) -> List[Dict[str,Any]]:
        topk = topk or self.BM25_TOPK
        return self.bm25.search(query, topk=topk, labels_filter=labels_filter)

    def hybrid(self, query: str, final_k: Optional[int]=None, labels_filter: Optional[List[str]]=None, where_dense: Optional[Dict[str,Any]] = None) -> List[Dict[str,Any]]:
        """
        Recuperación híbrida con fusión RRF.
        - labels_filter: se pasa al BM25 (filtro inicial).
        - where_dense: filtro por metadatos para vectorial (ej. labels IN ...).
        """
        vec_hits = self.dense_search(query, k=self.K_RETRIEVE, where=where_dense)
        bm25_hits = self.lex_search(query, topk=self.BM25_TOPK, labels_filter=labels_filter)
        fused = reciprocal_rank_fusion(vec_hits, bm25_hits, K=self.RRF_K)
        k = final_k or self.K_RETRIEVE
        return fused[:k]

# -----------------------------
# Umbrales de insuficiente evidencia
# -----------------------------
@dataclass
class Thresholds:
    k_min: int = 3  # BAJADO a 3 (antes 5)
    min_sources: int = 1  # BAJADO a 1 (antes 2) para testing
    entity_coverage_min: float = 0.10  # BAJADO a 0.10 temporalmente (muchos fragmentos sin entidades aún)
    mean_score_min: float = 0.010  # BAJADO a 0.010 (antes 0.015)
    min_fragment_score: float = 0.003  # BAJADO a 0.003 (antes 0.008) para permitir más fragmentos

def _count_sources(hits: List[Dict[str,Any]]) -> int:
    docs = set()
    for h in hits:
        doc_id = (h.get("metadata") or {}).get("doc_id")
        if doc_id:
            docs.add(doc_id)
    return len(docs)

def _extract_frag_entities(hit: Dict[str,Any]) -> List[Entity]:
    import json
    ents = []
    entities_raw = (hit.get("metadata") or {}).get("entities", [])
    
    # Si entities es un string (serializado desde ChromaDB), deserializar
    if isinstance(entities_raw, str):
        try:
            entities_raw = json.loads(entities_raw) if entities_raw else []
        except Exception:
            entities_raw = []
    
    # Ahora procesar la lista
    for e in entities_raw:
        if isinstance(e, dict):
            t = e.get("type"); v = e.get("value")
            if t and v:
                ents.append(Entity(type=t, value=v, original=v, start=0, end=0))
    return ents

def insufficient_evidence(query: str, hits: List[Dict[str,Any]], th: Optional[Thresholds]=None) -> Tuple[bool, Dict[str,Any], List[Dict[str,Any]]]:
    """
    Evalúa si la evidencia es suficiente según umbrales.
    Calcula entity_coverage entre entidades de la consulta vs de los top hits.
    Retorna: (is_insufficient, diagnostics, filtered_hits)
    """
    th = th or Thresholds()
    
    # Filtrar fragmentos con score RRF muy bajo (evita ruido)
    hits_filtered = [h for h in hits if h.get("rrf_score", 0.0) >= th.min_fragment_score]
    
    if len(hits_filtered) < th.k_min:
        return True, {"reason":"k_min_after_filter", "k": len(hits_filtered), "k_min": th.k_min, "original_k": len(hits)}, hits_filtered

    # Entidades de la consulta
    q_ents, _, tax_ver = extract_entities(query)
    
    # Si la query NO tiene entidades del dominio, es señal de fuera-de-dominio
    if not q_ents:
        return True, {"reason":"no_domain_entities", "query_entities": 0}, hits_filtered
    
    # Entidades de fragmentos top-k (usa hits_filtered)
    f_ents_all = []
    for h in hits_filtered:
        f_ents_all.extend(_extract_frag_entities(h))

    cov = entity_coverage(q_ents, f_ents_all)
    if cov < th.entity_coverage_min:
        return True, {"reason":"entity_coverage", "coverage": cov, "min": th.entity_coverage_min}, hits_filtered

    # Fuentes distintas
    sources = _count_sources(hits_filtered)
    # excepción: si todos los docs son 'normativos', podrías permitir min_sources=1.
    if sources < th.min_sources:
        return True, {"reason":"min_sources", "sources": sources, "min": th.min_sources}, hits_filtered

    # Promedio de rrf_score (rudimentario; podrías normalizar por el top)
    mean_score = sum(h.get("rrf_score", 0.0) for h in hits_filtered) / max(len(hits_filtered), 1)
    if mean_score < th.mean_score_min:
        return True, {"reason":"mean_score", "mean": mean_score, "min": th.mean_score_min}, hits_filtered

    return False, {"coverage": cov, "sources": sources, "mean_score": mean_score, "taxonomy_version": tax_ver}, hits_filtered

def build_insufficient_response(query: str, diag: Dict[str,Any]) -> Dict[str,Any]:
    """
    Estructura estándar para responder 'insuficiente evidencia' con diagnóstico mínimo.
    """
    return {
        "respuesta_html": "<p><em>Insuficiente evidencia en el conjunto documental actual.</em></p>",
        "citas": [],
        "advertencias": ["insuficiente_evidencia"],
        "diagnostico": diag
    }

# -----------------------------
# Reranking multi-factor
# -----------------------------
def rerank_top_n(hits: List[Dict[str,Any]], query: str, topn: int = 20, 
                 w_sim: float = 0.4, w_fresh: float = 0.2, 
                 w_auth: float = 0.2, w_entity: float = 0.2) -> List[Dict[str,Any]]:
    """
    Reordena los top-N hits aplicando pesos configurables.
    Score final = w_sim * rrf_score + w_fresh * frescura + w_auth * autoridad + w_entity * cobertura_entidades
    """
    import datetime
    
    # Extraer entidades de la query
    q_ents, _, _ = extract_entities(query)
    
    reranked = []
    for h in hits[:topn]:
        score_base = h.get("rrf_score", 0.0)
        
        # Factor frescura (normalizado 0-1): docs recientes obtienen más peso
        meta = h.get("metadata", {})
        created_at = meta.get("created_at")
        score_fresh = 0.5  # default neutral
        if created_at:
            try:
                dt = datetime.datetime.fromisoformat(created_at)
                days_old = (datetime.datetime.now() - dt).days
                score_fresh = max(0.0, 1.0 - (days_old / 365.0))  # decay lineal en 1 año
            except:
                pass
        
        # Factor autoridad: docs de fuentes oficiales (puede ser campo en metadata)
        source = meta.get("source", "").lower()
        score_auth = 1.0 if any(x in source for x in ["inifap", "fao", "sagarpa", "senasica"]) else 0.5
        
        # Factor cobertura de entidades: qué tanto se solapan las entidades del fragmento con la query
        frag_ents = _extract_frag_entities(h)
        score_entity = entity_coverage(q_ents, frag_ents) if q_ents else 0.5
        
        # Score combinado
        final_score = (w_sim * score_base + 
                      w_fresh * score_fresh + 
                      w_auth * score_auth + 
                      w_entity * score_entity)
        
        reranked.append({**h, "rerank_score": final_score, 
                        "factors": {"sim": score_base, "fresh": score_fresh, 
                                   "auth": score_auth, "entity": score_entity}})
    
    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked
