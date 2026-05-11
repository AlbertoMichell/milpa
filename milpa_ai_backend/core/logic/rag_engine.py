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
# Re-ranking por coincidencia de términos
# -----------------------------
def rerank_by_term_coverage(query: str, hits: List[Dict[str,Any]], fragment_texts: Dict[str, str]) -> List[Dict[str,Any]]:
    """
    Aplica boost al score según cuántos términos únicos de la query aparecen en el fragmento.
    Esto prioriza fragmentos con mayor cobertura de la pregunta.
    """
    import re
    
    # Extraer términos significativos de la query (sin stopwords básicos)
    stopwords = {'de', 'el', 'la', 'los', 'las', 'un', 'una', 'es', 'en', 'del', 'al', 'por', 'para', 
                 'que', 'qué', 'cuál', 'cuáles', 'cómo', 'a', 'y', 'o', 'u', 'e'}
    query_lower = query.lower()
    query_terms = [w for w in re.findall(r'\w+', query_lower) if len(w) > 2 and w not in stopwords]
    
    if not query_terms:
        return hits
    
    # Calcular boost para cada hit
    reranked = []
    for hit in hits:
        fid = hit["fragment_id"]
        text = fragment_texts.get(fid, "").lower()
        
        # Contar términos que aparecen en el fragmento
        matched_terms = sum(1 for term in query_terms if term in text)
        coverage_ratio = matched_terms / len(query_terms)
        
        # Boost: multiplicar score original por (1 + coverage_ratio)
        # Esto favorece fragmentos con más términos sin eliminar los que tienen pocos
        original_score = hit.get("rrf_score", 0.0)
        boosted_score = original_score * (1.0 + coverage_ratio * 0.5)  # Boost moderado del 50%
        
        reranked.append({
            **hit,
            "rrf_score": boosted_score,
            "original_score": original_score,
            "term_coverage": coverage_ratio,
            "matched_terms": matched_terms
        })
    
    # Re-ordenar por score boosted
    reranked.sort(key=lambda x: x["rrf_score"], reverse=True)
    return reranked


def apply_crop_focus_to_hits(
    hits: List[Dict[str, Any]],
    fragment_texts: Dict[str, str],
    fragment_entities_json: Dict[str, Optional[str]],
    crop_focus_norm: Optional[str],
    retrieval_scope: str,
    enabled: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Anota cada hit con crop_hints / crop_multi y aplica factor multiplicativo si
    hay foco y ámbito distinto de global.
    """
    from milpa_ai_backend.core.logic.crop_hints import (
        infer_crop_hints,
        adjustment_factor,
        should_exclude_strict,
    )

    trace: Dict[str, Any] = {
        "crop_focus": crop_focus_norm,
        "retrieval_scope": retrieval_scope,
        "enabled": enabled,
        "per_fragment": [],
    }

    if not enabled or not crop_focus_norm or retrieval_scope == "global":
        out: List[Dict[str, Any]] = []
        for h in hits:
            fid = h["fragment_id"]
            hints, multi = infer_crop_hints(
                fragment_texts.get(fid, ""),
                fragment_entities_json.get(fid),
            )
            out.append(
                {
                    **h,
                    "crop_hints": hints,
                    "crop_multi": multi,
                    "crop_adjust_factor": 1.0,
                    "crop_adjust_reason": "global_scope",
                }
            )
            trace["per_fragment"].append(
                {
                    "fragment_id": fid,
                    "hints": hints,
                    "multi_crop": multi,
                    "factor": 1.0,
                    "excluded": False,
                }
            )
        return out, trace

    adjusted: List[Dict[str, Any]] = []
    for h in hits:
        fid = h["fragment_id"]
        text = fragment_texts.get(fid, "")
        ents = fragment_entities_json.get(fid)
        hints, multi = infer_crop_hints(text, ents)
        factor, reason = adjustment_factor(
            crop_focus_norm, hints, multi, text, retrieval_scope
        )
        excluded = (
            retrieval_scope == "crop_strict"
            and should_exclude_strict(crop_focus_norm, hints, multi)
        )
        trace["per_fragment"].append(
            {
                "fragment_id": fid,
                "hints": hints,
                "multi_crop": multi,
                "factor": factor,
                "reason": reason,
                "excluded": excluded,
            }
        )
        if excluded:
            continue
        new_score = float(h.get("rrf_score", 0.0)) * factor
        adjusted.append(
            {
                **h,
                "rrf_score": new_score,
                "crop_hints": hints,
                "crop_multi": multi,
                "crop_adjust_factor": factor,
                "crop_adjust_reason": reason,
            }
        )

    adjusted.sort(key=lambda x: x["rrf_score"], reverse=True)
    return adjusted, trace

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
    # Mínimos pensados para queries muy específicas (ej. "Distancia siembra calabaza")
    # donde BM25 puede sólo encontrar 1-2 hits muy buenos. Mejor responder con poca
    # evidencia que dar "insuficiente" cuando hay un manual exacto.
    k_min: int = 1
    min_sources: int = 1
    entity_coverage_min: float = 0.10
    mean_score_min: float = 0.005
    min_fragment_score: float = 0.001

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

    # Fallback tolerante: si el filtro por min_fragment_score nos deja sin nada y
    # había hits arriba, conservamos los hits originales en orden actual. Esto
    # evita que penalizaciones por crop_focus + scores RRF muy pequeños vacíen
    # la respuesta cuando sí existe evidencia razonable (caso típico: querys con
    # signos de interrogación que reducen el score absoluto pero mantienen orden).
    if not hits_filtered and hits:
        hits_filtered = list(hits)

    if len(hits_filtered) < th.k_min:
        return True, {"reason": "k_min_after_filter", "k": len(hits_filtered), "k_min": th.k_min, "original_k": len(hits)}, hits_filtered

    q_ents, _, tax_ver = extract_entities(query)
    cov = 0.0
    # No rechazamos por entity_coverage: con la nueva síntesis, los fragmentos
    # se ordenan por crop_focus y la respuesta cita la mejor evidencia disponible
    # incluso si las entidades cruzan cultivos. Mantenemos el cálculo en `cov`
    # para diagnóstico/observabilidad sin abortar.
    if q_ents:
        f_ents_all: List[Dict[str, Any]] = []
        for h in hits_filtered:
            f_ents_all.extend(_extract_frag_entities(h))
        cov = entity_coverage(q_ents, f_ents_all)

    sources = _count_sources(hits_filtered)
    if sources < th.min_sources:
        return True, {"reason": "min_sources", "sources": sources, "min": th.min_sources}, hits_filtered

    mean_score = sum(h.get("rrf_score", 0.0) for h in hits_filtered) / max(len(hits_filtered), 1)
    if mean_score < th.mean_score_min:
        return True, {"reason": "mean_score", "mean": mean_score, "min": th.mean_score_min}, hits_filtered

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
