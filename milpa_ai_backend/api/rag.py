# milpa_ai_backend/api/rag.py
# ------------------------------------------------------------
# Endpoint de consulta RAG híbrida (BM25 + vectorial).
# Retorna fragmentos relevantes con metadatos y score.
# ------------------------------------------------------------
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json as json_module

logger = logging.getLogger(__name__)

from milpa_ai_backend.core.logic.rag_engine import HybridRetriever, insufficient_evidence, build_insufficient_response, Thresholds
from milpa_ai_backend.core.logic.embeddings import EmbeddingModel
from milpa_ai_backend.core.logic.vectordb import VectorStore
from milpa_ai_backend.core.logic.bm25 import BM25Index
from milpa_ai_backend.core.logic.db import get_conn

router = APIRouter()

# Instancias globales (singleton pattern)
_embedder: Optional[EmbeddingModel] = None
_vector_store: Optional[VectorStore] = None
_bm25_index: Optional[BM25Index] = None
_retriever: Optional[HybridRetriever] = None


def get_retriever() -> HybridRetriever:
    """Lazy initialization del retriever híbrido."""
    global _embedder, _vector_store, _bm25_index, _retriever
    
    if _retriever is not None:
        return _retriever
    
    # Usar índices ya configurados (por tests) o crear nuevos
    if _embedder is None:
        _embedder = EmbeddingModel()
    if _vector_store is None:
        _vector_store = VectorStore()
    if _bm25_index is None:
        _bm25_index = BM25Index()
    
    _retriever = HybridRetriever(
        vector_store=_vector_store,
        bm25_index=_bm25_index,
        embedder=_embedder
    )
    
    return _retriever


class QueryRequest(BaseModel):
    query: str
    k: int = 8
    mode: str = "hybrid"  # "hybrid", "dense", "lex"
    labels_filter: Optional[List[str]] = None


class FragmentResponse(BaseModel):
    fragment_id: str
    text: str
    score: float
    doc_id: str
    doc_title: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    labels: List[str] = []
    entities: List[Dict[str, Any]] = []


class QueryResponse(BaseModel):
    query: str
    fragments: List[FragmentResponse]
    total_retrieved: int
    mode: str
    insufficient_evidence: bool = False
    diagnostics: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None  # Respuesta generada
    answer_mode: Optional[str] = None  # Modo de generación usado
    citations: Optional[List[str]] = None  # Citaciones


@router.post("/api/query", response_model=QueryResponse)
async def query_rag(req: QueryRequest):
    """
    Endpoint de consulta RAG híbrida con generación de respuesta.
    
    Modos disponibles:
    - hybrid: BM25 + vectorial con fusión RRF (por defecto)
    - dense: Solo búsqueda vectorial
    - lex: Solo BM25
    
    Retorna fragmentos rankeados + respuesta generada con LLM.
    """
    retriever = get_retriever()
    
    # Ejecutar búsqueda según modo
    if req.mode == "dense":
        hits = retriever.dense_search(req.query, k=req.k)
    elif req.mode == "lex":
        hits = retriever.lex_search(req.query, topk=req.k * 10, labels_filter=req.labels_filter)
        hits = hits[:req.k]  # Limitar a k
    else:  # hybrid
        hits = retriever.hybrid(
            req.query,
            final_k=req.k,
            labels_filter=req.labels_filter
        )
    
    # Evaluar evidencia insuficiente y obtener hits filtrados por score
    is_insufficient, diag, hits_filtered = insufficient_evidence(req.query, hits)
    
    # Si insufficient evidence, retornar inmediatamente sin procesar fragmentos
    if is_insufficient:
        fallback_response = build_insufficient_response(req.query, diag)
        return QueryResponse(
            query=req.query,
            fragments=[],  # No retornar fragmentos cuando evidencia es insuficiente
            total_retrieved=0,
            mode=req.mode,
            insufficient_evidence=True,
            diagnostics=diag,
            answer=fallback_response.get("respuesta_html", "No hay información suficiente."),
            answer_mode="insufficient",
            citations=None
        )
    
    # Usar hits_filtered para cargar textos completos y metadatos desde BD
    fragments_out: List[FragmentResponse] = []
    fragments_for_generation = []
    
    with get_conn() as conn:
        cur = conn.cursor()
        for h in hits_filtered:
            fid = h["fragment_id"]
            cur.execute("""
                SELECT f.text, f.doc_id, f.page_start, f.page_end, d.title
                FROM fragments f
                LEFT JOIN docs d ON f.doc_id = d.doc_id
                WHERE f.fragment_id = ?
            """, (fid,))
            row = cur.fetchone()
            
            if not row:
                continue
            
            text, doc_id, page_start, page_end, doc_title = row
            metadata = h.get("metadata", {})
            
            fragment_resp = FragmentResponse(
                fragment_id=fid,
                text=text or "",
                score=h.get("rrf_score", h.get("score", 0.0)),
                doc_id=doc_id or "",
                doc_title=doc_title,
                page_start=page_start,
                page_end=page_end,
                labels=metadata.get("labels", []),
                entities=json_module.loads(metadata.get("entities", "[]")) if isinstance(metadata.get("entities"), str) else metadata.get("entities", [])
            )
            
            fragments_out.append(fragment_resp)
            
            # Para generación
            fragments_for_generation.append({
                "text": text or "",
                "doc_id": doc_id or "",
                "page_start": page_start,
                "score": h.get("rrf_score", h.get("score", 0.0))
            })
    
    # Generar respuesta con síntesis anti-alucinación
    answer_text = None
    answer_mode = None
    citations = None
    faithfulness = None
    
    try:
        from core.logic.synthesis import compose_answer
        result = compose_answer(
            query=req.query,
            fragments=fragments_for_generation,
            max_length=500
        )
        
        answer_text = result.get("respuesta_html")
        answer_mode = "synthesis"
        
        # Convertir citas de dict a string para compatibilidad con QueryResponse
        citas_dict = result.get("citas", [])
        citations = [
            f"[{c['citation_id']}] Doc: {c['doc_id'][:8]}... página {c.get('page', '?')}" 
            for c in citas_dict
        ]
        
        faithfulness = result.get("faithfulness")
        
        # Advertencia si baja fidelidad
        if faithfulness and faithfulness < 0.85:
            print(f"Warning: Baja fidelidad en respuesta (faithfulness={faithfulness:.2f})")
    except Exception as e:
        print(f"Warning: Error en síntesis de respuesta: {e}")
        import traceback
        traceback.print_exc()
        # Fallback: concatenar fragmentos
        if fragments_out:
            answer_text = "\n\n".join([f"[{i+1}] {f.text[:500]}..." for i, f in enumerate(fragments_out[:3])])
            answer_mode = "fallback"
    
    return QueryResponse(
        query=req.query,
        fragments=fragments_out,
        total_retrieved=len(fragments_out),
        mode=req.mode,
        insufficient_evidence=False,
        diagnostics=None,
        answer=answer_text,
        answer_mode=answer_mode,
        citations=citations
    )


@router.post("/api/index/rebuild")
async def rebuild_indexes():
    """
    Reconstruye índices BM25 y vectorial desde la BD.
    Útil después de indexar nuevos documentos.
    """
    global _embedder, _vector_store, _bm25_index, _retriever
    
    # Invalidar singleton para forzar recreación
    _embedder = None
    _vector_store = None
    _bm25_index = None
    _retriever = None
    
    retriever = get_retriever()
    
    # Cargar todos los fragmentos de la BD con entidades
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT f.fragment_id, f.text, f.doc_id, d.source, f.entities
            FROM fragments f
            LEFT JOIN docs d ON f.doc_id = d.doc_id
        """)
        rows = cur.fetchall()
    
    if not rows:
        raise HTTPException(status_code=404, detail="No hay fragmentos para indexar")
    
    # Preparar documentos para indexación
    docs_for_bm25 = []
    docs_for_vector = []
    texts_for_embedding = []
    
    for fragment_id, text, doc_id, source, entities_json in rows:
        if not text:
            continue
        
        # Deserializar entidades desde JSON
        import json as json_module
        entities_list = []
        if entities_json:
            try:
                entities_list = json_module.loads(entities_json)
            except Exception:
                entities_list = []
        
        # BM25
        docs_for_bm25.append({
            "fragment_id": fragment_id,
            "text": text,
            "labels": [],  # TODO: extraer labels si existen
            "doc_id": doc_id or "",
            "entities": entities_list
        })
        
        # Vector - pasar entidades serializadas como metadata
        texts_for_embedding.append(text)
        entities_json_str = json_module.dumps(entities_list)
        docs_for_vector.append({
            "fragment_id": fragment_id,
            "doc_id": doc_id or "",
            "source": source or "",
            "entities": entities_json_str  # Serializar para ChromaDB metadata
        })
    
    # Reset índices
    retriever.bm25.reset()
    retriever.vs.reset()
    
    # Indexar BM25
    retriever.bm25.index_many(docs_for_bm25)
    
    # Generar embeddings y guardar en vector store
    embeddings = retriever.embedder.embed_texts(texts_for_embedding)
    
    ids = [d["fragment_id"] for d in docs_for_vector]
    metadatas = [
        {
            "fragment_id": d["fragment_id"],
            "doc_id": d["doc_id"],
            "source": d["source"],
            "entities": d.get("entities", "[]"),  # JSON string de entidades
            # ChromaDB no acepta listas/dict en metadatos, solo str/int/float/bool
        }
        for d in docs_for_vector
    ]
    
    retriever.vs.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
    
    # DEBUG: verificar qué se guardó DESPUÉS de agregar
    try:
        with open(debug_path, 'a') as f:
            saved = retriever.vs.col.get(ids=[ids[0]], include=['metadatas'])
            if saved and saved['metadatas']:
                f.write(f"\nGuardado en ChromaDB: {saved['metadatas'][0]}\n")
                f.write(f"Keys guardadas: {list(saved['metadatas'][0].keys())}\n")
        logger.warning(f"DEBUG verification written to {debug_path}")
    except Exception as e:
        logger.error(f"ERROR writing debug verification: {e}")
    
    return {
        "status": "success",
        "indexed_fragments": len(rows),
        "bm25_docs": len(docs_for_bm25),
        "vector_docs": len(docs_for_vector)
    }
