from __future__ import annotations

from typing import Any, Dict, List, Optional

from milpa_ai_backend.api.rag import QueryRequest, query_rag

from .diagnostics import crop_status_line, crop_display_label
from .intent import IntentResult


def should_query_rag(intent: IntentResult, mode: str) -> bool:
    if mode == "biblioteca":
        return True
    if intent.intent in {
        "library_question",
        "pest_or_disease",
        "fertilization",
        "soil_condition",
        "climate_risk",
    }:
        return True
    return False


def _build_rag_query(message: str, target_crop: Optional[Dict[str, Any]], active_crops: List[Dict[str, Any]]) -> str:
    if target_crop:
        status = crop_status_line(target_crop)
        return (
            "Eres un asistente agricola experto. "
            f"Cultivo: {target_crop.get('crop_name')}. "
            f"Contexto: {status} "
            f"Pregunta del agricultor: \"{message}\". "
            "Responde de forma practica y breve, sin historia ni origen."
        )
    if active_crops:
        names = ", ".join(crop_display_label(c) for c in active_crops)
        return (
            f"Responde de forma concisa a esta consulta: \"{message}\". "
            f"Cultivos activos: {names}. Evita historia u origen."
        )
    return f"Responde de forma concisa a esta consulta: \"{message}\"."


def _build_rag_params(context: Dict[str, Any]) -> Dict[str, Any]:
    if context.get("rag_conflict") and context.get("requested_crop_name"):
        return {
            "crop_focus": context["requested_crop_name"],
            "retrieval_scope": "crop_boost",
        }
    target = context.get("target_crop")
    if target:
        return {
            "crop_focus": target.get("crop_name"),
            "user_crop_id": int(target.get("id")),
            "retrieval_scope": "crop_boost",
        }
    return {"retrieval_scope": "global"}


async def query_rag_for_message(
    message: str,
    context: Dict[str, Any],
    intent: IntentResult,
) -> Dict[str, Any]:
    try:
        query = _build_rag_query(message, context.get("target_crop"), context.get("active_crops") or [])
        params = _build_rag_params(context)
        req = QueryRequest(query=query, k=8, mode="hybrid", **params)
        resp = await query_rag(req)
        return {
            "used": True,
            "query": query,
            "answer": resp.answer,
            "answer_mode": resp.answer_mode,
            "insufficient_evidence": bool(resp.insufficient_evidence),
            "citations": resp.citations or [],
            "retrieval_scope": params.get("retrieval_scope", "global"),
            "crop_trace": resp.crop_trace,
        }
    except Exception as exc:
        return {
            "used": False,
            "error": str(exc),
        }
