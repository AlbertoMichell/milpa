from __future__ import annotations

from typing import Any, Dict, List, Optional

from milpa_ai_backend.api.rag import QueryRequest, query_rag

from .diagnostics import crop_status_line, crop_display_label, sensor_summary
from .intent import IntentResult


_RAG_INTENTS = {
    "library_question",
    "pest_or_disease",
    "fertilization",
    "soil_condition",
    "climate_risk",
}


def should_query_rag(intent: IntentResult, mode: str) -> bool:
    if intent.is_garbage:
        return False
    if mode == "biblioteca":
        return True
    return intent.intent in _RAG_INTENTS


def _profile_brief(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return "sin perfil agronómico disponible"

    parts: List[str] = []
    sm_min = profile.get("optimal_soil_moisture_min")
    sm_max = profile.get("optimal_soil_moisture_max")
    t_min = profile.get("optimal_temp_min")
    t_max = profile.get("optimal_temp_max")
    ph_min = profile.get("optimal_ph_min")
    ph_max = profile.get("optimal_ph_max")

    if sm_min is not None or sm_max is not None:
        parts.append(f"humedad suelo óptima {sm_min if sm_min is not None else '?'}-{sm_max if sm_max is not None else '?'}%")
    if t_min is not None or t_max is not None:
        parts.append(f"temperatura óptima {t_min if t_min is not None else '?'}-{t_max if t_max is not None else '?'} °C")
    if ph_min is not None or ph_max is not None:
        parts.append(f"pH óptimo {ph_min if ph_min is not None else '?'}-{ph_max if ph_max is not None else '?'}")

    return "; ".join(parts) if parts else "perfil agronómico sin rangos críticos"


def _health_brief(health: Optional[Dict[str, Any]]) -> str:
    if not health:
        return "sin salud calculada"
    label = health.get("label") or "sin evaluar"
    score = health.get("score")
    summary = health.get("summary") or ""
    if score is not None:
        return f"{label} (score {score}). {summary}".strip()
    return f"{label}. {summary}".strip()


def _build_rag_query(
    message: str,
    target_crop: Optional[Dict[str, Any]],
    active_crops: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
    health: Optional[Dict[str, Any]],
    mode: str,
) -> str:
    if mode == "biblioteca" and not target_crop:
        return (
            f"Consulta de biblioteca MILPA: \"{message}\". "
            "Responde con base en documentos cargados, de forma clara y con enfoque agrícola."
        )

    if target_crop:
        return (
            "Eres el componente documental de apoyo de AgroBot MILPA. "
            "Tu respuesta será usada solo como evidencia técnica complementaria; "
            "NO debes desplazar ni contradecir sensores, perfil agronómico ni salud calculada. "
            "Evita historia, origen y definiciones generales si no fueron solicitadas explícitamente. "
            f"Cultivo objetivo: {target_crop.get('crop_name')}. "
            f"Estado registrado: {crop_status_line(target_crop)} "
            f"Sensores actuales: {sensor_summary(target_crop) or 'sin sensores recientes'}. "
            f"Perfil: {_profile_brief(profile)}. "
            f"Salud calculada: {_health_brief(health)}. "
            f"Pregunta del agricultor: \"{message}\". "
            "Devuelve solo manejo técnico aplicable y breve."
        )

    if active_crops:
        names = ", ".join(crop_display_label(c) for c in active_crops)
        return (
            "Consulta desde AgroBot MILPA con varios cultivos activos. "
            f"Cultivos activos: {names}. "
            f"Pregunta del agricultor: \"{message}\". "
            "Responde de forma práctica, sin historia ni origen, y evita asumir un cultivo único."
        )

    return (
        f"Consulta de biblioteca MILPA: \"{message}\". "
        "No hay cultivos activos registrados; responde solo desde documentos."
    )


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
    mode: str = "auto",
    profile: Optional[Dict[str, Any]] = None,
    health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        query = _build_rag_query(
            message=message,
            target_crop=context.get("target_crop"),
            active_crops=context.get("active_crops") or [],
            profile=profile,
            health=health,
            mode=mode,
        )
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
            "intent": intent.intent,
            "role": "evidence_only" if mode == "parcela" else "library_answer",
        }
    except Exception as exc:
        return {
            "used": False,
            "error": str(exc),
            "intent": intent.intent,
        }
