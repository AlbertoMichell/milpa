# milpa_ai_backend/api/rag.py
# ------------------------------------------------------------
# Endpoint de consulta RAG híbrida (BM25 + vectorial).
# Retorna fragmentos relevantes con metadatos y score.
# ------------------------------------------------------------
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
import json as json_module

logger = logging.getLogger(__name__)

from milpa_ai_backend.core.config import settings
from milpa_ai_backend.core.logic.rag_engine import (
    HybridRetriever,
    insufficient_evidence,
    build_insufficient_response,
    rerank_by_term_coverage,
    apply_crop_focus_to_hits,
)
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
    crop_focus: Optional[str] = Field(
        default=None,
        description="Cultivo normalizado internamente; solo afecta recuperación si retrieval_scope != global",
    )
    user_crop_id: Optional[int] = Field(
        default=None,
        description="Si se envía, resuelve crop_name desde user_crops (toma precedencia sobre crop_focus textual)",
    )
    retrieval_scope: Literal["global", "crop_boost", "crop_strict"] = Field(
        default="global",
        description="global=mismo comportamiento histórico; crop_boost/crop_strict activan reescritura y filtro por cultivo",
    )


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
    # Metadatos para visor por coordenadas y citas precisas:
    bbox: Optional[List[float]] = None
    source: Optional[str] = None  # "native" | "ocr" | "table"
    render_url: Optional[str] = None
    locate_url: Optional[str] = None


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
    crop_trace: Optional[Dict[str, Any]] = None  # Diagnóstico opcional de foco de cultivo


def _resolve_effective_crop_focus(conn, req: QueryRequest):
    from milpa_ai_backend.core.logic.crop_hints import normalize_crop_focus

    if req.user_crop_id is not None:
        try:
            row = conn.execute(
                "SELECT crop_name FROM user_crops WHERE id = ?",
                (int(req.user_crop_id),),
            ).fetchone()
            if row and row[0]:
                return normalize_crop_focus(str(row[0]))
        except Exception:
            logger.debug("user_crops no disponible o sin fila para user_crop_id", exc_info=True)
    if req.crop_focus:
        return normalize_crop_focus(req.crop_focus)
    return None


def _detect_crop_in_query(conn, query: str):
    """Si la query menciona un cultivo del catálogo crop_profiles, devuelve su nombre normalizado."""
    from milpa_ai_backend.core.logic.crop_hints import normalize_crop_focus

    if not query:
        return None
    q_norm = normalize_crop_focus(query) or ""
    if not q_norm:
        return None
    try:
        rows = conn.execute("SELECT crop_name FROM crop_profiles").fetchall()
    except Exception:
        return None
    candidates = []
    for (name,) in rows:
        n = normalize_crop_focus(str(name)) or ""
        if n and len(n) >= 3 and n in q_norm:
            candidates.append((len(n), n))
    if not candidates:
        return None
    candidates.sort(reverse=True)  # prefer match más largo
    return candidates[0][1]


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

    auto_focus = False
    with get_conn() as conn:
        effective_crop = _resolve_effective_crop_focus(conn, req)
        # Auto-detect: si el cliente no envió crop_focus y la query menciona un cultivo del catálogo,
        # activamos crop_boost (no estricto) para que la respuesta priorice el cultivo correcto.
        if (
            effective_crop is None
            and req.crop_focus is None
            and req.user_crop_id is None
            and req.retrieval_scope == "global"
            and bool(getattr(settings, "RAG_CROP_AWARE", True))
        ):
            detected = _detect_crop_in_query(conn, req.query)
            if detected:
                effective_crop = detected
                auto_focus = True

    effective_scope = "crop_boost" if auto_focus else req.retrieval_scope
    apply_crop = (
        bool(getattr(settings, "RAG_CROP_AWARE", True))
        and effective_crop is not None
        and effective_scope != "global"
    )
    search_query = req.query
    if apply_crop:
        search_query = f"documentacion agronomica sobre {effective_crop}: {req.query}"
        logger.info(
            "RAG query crop-aware: focus=%s scope=%s user_crop_id=%s auto=%s",
            effective_crop,
            effective_scope,
            req.user_crop_id,
            auto_focus,
        )

    # Ejecutar búsqueda según modo (search_query respeta compatibilidad si retrieval_scope=global)
    if req.mode == "dense":
        hits = retriever.dense_search(search_query, k=req.k)
    elif req.mode == "lex":
        hits = retriever.lex_search(search_query, topk=req.k * 10, labels_filter=req.labels_filter)
    else:
        hits = retriever.hybrid(
            search_query,
            final_k=req.k * 2,
            labels_filter=req.labels_filter,
        )

    # Uniformar score → rrf_score: dense y lex devuelven 'score' pero el resto del
    # pipeline (rerank, insufficient_evidence, response) lee 'rrf_score'. Esto evita
    # que el modo lex caiga siempre en insufficient_evidence por filtrado de score=0.
    for h in hits:
        if "rrf_score" not in h or h.get("rrf_score") in (None, 0.0):
            sc = h.get("score")
            if sc is not None:
                h["rrf_score"] = float(sc)

    fragment_texts: Dict[str, str] = {}
    fragment_entities_json: Dict[str, Optional[str]] = {}
    if hits:
        ids = [h["fragment_id"] for h in hits]
        placeholders = ",".join(["?"] * len(ids))
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT fragment_id, text, entities FROM fragments WHERE fragment_id IN ({placeholders})",
                ids,
            )
            for row in cur.fetchall():
                fragment_texts[row[0]] = row[1] or ""
                fragment_entities_json[row[0]] = row[2]

    if req.mode == "hybrid":
        hits = rerank_by_term_coverage(search_query, hits, fragment_texts)

    hits, crop_trace = apply_crop_focus_to_hits(
        hits,
        fragment_texts,
        fragment_entities_json,
        effective_crop if apply_crop else None,
        effective_scope if apply_crop else "global",
        enabled=bool(getattr(settings, "RAG_CROP_AWARE", True) and apply_crop),
    )
    if apply_crop and crop_trace:
        crop_trace["auto_focus_from_query"] = auto_focus

    hits = hits[: req.k]

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
            citations=None,
            crop_trace=crop_trace if apply_crop else None,
        )
    
    # Usar hits_filtered para cargar metadatos completos desde BD (textos ya cargados arriba)
    fragments_out: List[FragmentResponse] = []
    fragments_for_generation = []
    
    with get_conn() as conn:
        cur = conn.cursor()
        for h in hits_filtered:
            fid = h["fragment_id"]
            
            # Reutilizar texto ya cargado en re-ranking
            text = fragment_texts.get(fid)
            if not text:
                # Fallback: cargar si no estaba en cache
                cur.execute("SELECT text FROM fragments WHERE fragment_id = ?", (fid,))
                row = cur.fetchone()
                text = row[0] if row else ""
            
            # Cargar metadatos adicionales
            cur.execute("""
                SELECT f.doc_id, f.page_start, f.page_end, d.title, f.bbox, f.source
                FROM fragments f
                LEFT JOIN docs d ON f.doc_id = d.doc_id
                WHERE f.fragment_id = ?
            """, (fid,))
            row = cur.fetchone()
            
            if not row:
                continue
            
            doc_id, page_start, page_end, doc_title, bbox_json, source = row
            metadata = h.get("metadata", {})

            bbox_parsed: Optional[List[float]] = None
            if bbox_json:
                try:
                    parsed = json_module.loads(bbox_json)
                    if isinstance(parsed, list) and len(parsed) >= 4:
                        bbox_parsed = [float(parsed[0]), float(parsed[1]), float(parsed[2]), float(parsed[3])]
                except Exception:
                    bbox_parsed = None

            render_url = None
            locate_url = None
            if doc_id and page_start:
                render_url = f"/api/documents/{doc_id}/render?page={page_start}&fragment_id={fid}"
                locate_url = f"/api/documents/{doc_id}/fragments/{fid}/locate"

            fragment_resp = FragmentResponse(
                fragment_id=fid,
                text=text or "",
                score=h.get("rrf_score", h.get("score", 0.0)),
                doc_id=doc_id or "",
                doc_title=doc_title,
                page_start=page_start,
                page_end=page_end,
                labels=metadata.get("labels", []),
                entities=json_module.loads(metadata.get("entities", "[]")) if isinstance(metadata.get("entities"), str) else metadata.get("entities", []),
                bbox=bbox_parsed,
                source=source,
                render_url=render_url,
                locate_url=locate_url,
            )

            fragments_out.append(fragment_resp)

            # Para generación (pistas de cultivo para ordenar en síntesis)
            fragments_for_generation.append({
                "text": text or "",
                "doc_id": doc_id or "",
                "doc_title": doc_title or "",
                "page_start": page_start,
                "fragment_id": fid,
                "score": h.get("rrf_score", h.get("score", 0.0)),
                "crop_hints": h.get("crop_hints", []),
                "crop_multi": h.get("crop_multi", False),
            })

    # Dedupe lexical antes de pasar a síntesis:
    #  - max 1 fragmento por (doc_id, página)
    #  - max 2 fragmentos por título normalizado (cubre casos donde varios doc_id
    #    representan el mismo manual reindexado bajo distinto id)
    #  - un fragmento por hash de los primeros 220 caracteres
    if len(fragments_for_generation) > 1:
        import re as _re_dedupe
        seen_dp: set = set()
        title_count: Dict[str, int] = {}
        seen_hash: set = set()
        deduped_gen: List[Dict[str, Any]] = []
        deduped_out: List[FragmentResponse] = []
        for fr_gen, fr_out in zip(fragments_for_generation, fragments_out):
            key = (fr_gen.get("doc_id", ""), str(fr_gen.get("page_start") or ""))
            title = (fr_gen.get("doc_title") or "").strip().lower()
            title = _re_dedupe.sub(r"\s+", " ", title)
            t = (fr_gen.get("text") or "").strip()
            t_norm = t[:220].lower()
            if key in seen_dp and key != ("", ""):
                continue
            if title and title_count.get(title, 0) >= 2:
                continue
            if t_norm and t_norm in seen_hash:
                continue
            seen_dp.add(key)
            if title:
                title_count[title] = title_count.get(title, 0) + 1
            if t_norm:
                seen_hash.add(t_norm)
            deduped_gen.append(fr_gen)
            deduped_out.append(fr_out)
        fragments_for_generation = deduped_gen
        fragments_out = deduped_out
    
    # Generar respuesta con síntesis anti-alucinación
    answer_text = None
    answer_mode = None
    citations = None
    faithfulness = None
    
    try:
        from milpa_ai_backend.core.logic.synthesis import compose_answer
        result = compose_answer(
            query=req.query,
            fragments=fragments_for_generation,
            max_length=500,
            crop_focus=effective_crop if apply_crop else None,
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
        citations=citations,
        crop_trace=crop_trace if apply_crop else None,
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
            ORDER BY f.doc_id, f.page_start, COALESCE(f.seq, 0), f.fragment_id
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
    
    logger.info(f"Índices reconstruidos: {len(docs_for_bm25)} BM25, {len(docs_for_vector)} vectoriales")
    
    return {
        "status": "success",
        "indexed_fragments": len(rows),
        "bm25_docs": len(docs_for_bm25),
        "vector_docs": len(docs_for_vector)
    }


def index_doc_fragments(doc_id: str) -> dict:
    """
    Indexa incrementalmente los fragmentos de un documento específico
    en BM25 y ChromaDB sin reconstruir todo el índice.

    Antes de añadir, purga del BM25 y de Chroma cualquier fragmento previo
    asociado al mismo ``doc_id`` para evitar fragmentos huérfanos cuando se
    re-ingesta el mismo documento (los nuevos fragments tienen UUIDs distintos
    a los antiguos, por lo que un upsert simple no los sobrescribiría).
    """
    retriever = get_retriever()

    try:
        retriever.bm25.delete_by_doc_id(doc_id)
    except Exception as e:
        logger.warning(f"BM25 purge previa fallo doc {doc_id[:12]}: {e}")
    try:
        retriever.vs.col.delete(where={"doc_id": doc_id})
    except Exception as e:
        logger.warning(f"Chroma purge previa fallo doc {doc_id[:12]}: {e}")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT f.fragment_id, f.text, f.doc_id, d.source, f.entities
            FROM fragments f
            LEFT JOIN docs d ON f.doc_id = d.doc_id
            WHERE f.doc_id = ?
            ORDER BY f.page_start, COALESCE(f.seq, 0), f.fragment_id
        """, (doc_id,))
        rows = cur.fetchall()

    if not rows:
        return {"indexed": 0}

    docs_for_bm25 = []
    texts_for_embedding = []
    docs_for_vector = []

    for fragment_id, text, did, source, entities_json in rows:
        if not text:
            continue

        entities_list = []
        if entities_json:
            try:
                entities_list = json_module.loads(entities_json)
            except Exception:
                pass

        docs_for_bm25.append({
            "fragment_id": fragment_id,
            "text": text,
            "labels": [],
            "doc_id": did or "",
            "entities": entities_list,
        })

        texts_for_embedding.append(text)
        docs_for_vector.append({
            "fragment_id": fragment_id,
            "doc_id": did or "",
            "source": source or "",
            "entities": json_module.dumps(entities_list),
        })

    # Indexar BM25 (incremental)
    retriever.bm25.index_many(docs_for_bm25)

    # Generar embeddings y añadir a ChromaDB (upsert para evitar duplicados)
    embeddings = retriever.embedder.embed_texts(texts_for_embedding)
    ids = [d["fragment_id"] for d in docs_for_vector]
    metadatas = [
        {
            "fragment_id": d["fragment_id"],
            "doc_id": d["doc_id"],
            "source": d["source"],
            "entities": d.get("entities", "[]"),
        }
        for d in docs_for_vector
    ]
    retriever.vs.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)

    logger.info(f"Indexados {len(docs_for_bm25)} fragmentos del doc {doc_id[:12]}...")
    return {"indexed": len(docs_for_bm25)}
