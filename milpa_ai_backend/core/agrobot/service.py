from __future__ import annotations

from typing import Any, Dict, Optional

from .composer import compose_answer
from .context_builder import build_context
from .evidence import query_rag_for_message, should_query_rag
from .intent import detect_intent, normalize_text
from .recommender_bridge import maybe_generate_recommendation
from .schemas import AgroBotRequest, AgroBotResponse


_SINGLE_CROP_FALLBACK_INTENTS = {
    "crop_status",
    "unknown",
    "water_balance",
    "harvest_date",
    "pest_or_disease",
    "fertilization",
    "soil_condition",
    "climate_risk",
}


def _select_profile(context: Dict[str, Any], target_crop: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not target_crop:
        return None
    profiles = context.get("profiles_by_name") or {}
    key = normalize_text(target_crop.get("crop_name"))
    return profiles.get(key)


def _pick_health(context: Dict[str, Any], target_crop: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not target_crop:
        return None
    crop_id = target_crop.get("id")
    for item in context.get("health_by_crop") or []:
        if str(item.get("crop_id")) == str(crop_id):
            return item
    return None


def _resolve_mode(req: AgroBotRequest, intent, context: Dict[str, Any]) -> str:
    if req.mode != "auto":
        return req.mode
    if intent.is_library:
        return "biblioteca"
    if not context.get("active_crops"):
        return "biblioteca"
    return "parcela"


def _resolve_target_crop(context: Dict[str, Any], intent, mode: str) -> Optional[Dict[str, Any]]:
    """
    Regla central:
    - En biblioteca no se usa cultivo activo para diagnosticar.
    - En parcela, target_crop solo es explícito o fallback cuando existe exactamente un cultivo activo.
    - Si hay varios cultivos activos y no se mencionó uno, no se toma el primero automáticamente.
    """
    active_crops = context.get("active_crops") or []
    requested_active = context.get("requested_active_crop")
    fallback_crop = context.get("fallback_crop")

    if mode == "biblioteca":
        context["target_crop"] = None
        context["target_crop_source"] = "none"
        # En biblioteca, preguntar historia/origen de un cultivo no activo no es conflicto.
        if intent.is_library:
            context["rag_conflict"] = False
        return None

    if requested_active:
        context["target_crop"] = requested_active
        context["target_crop_source"] = "explicit"
        return requested_active

    if len(active_crops) == 1 and intent.intent in _SINGLE_CROP_FALLBACK_INTENTS:
        context["target_crop"] = fallback_crop
        context["target_crop_source"] = "fallback_single_crop"
        return fallback_crop

    context["target_crop"] = None
    context["target_crop_source"] = "none"
    return None


def _build_context_payload(
    context: Dict[str, Any],
    target_crop: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "active_crops_count": len(context.get("active_crops") or []),
        "target_crop_source": context.get("target_crop_source", "none"),
    }

    if target_crop:
        payload["sensors"] = {
            "soil_moisture": target_crop.get("soil_moisture"),
            "air_temp": target_crop.get("air_temp"),
            "air_humidity": target_crop.get("air_humidity"),
            "light": target_crop.get("light"),
            "precipitation": target_crop.get("precipitation"),
            "wind_speed": target_crop.get("wind_speed"),
        }

    if context.get("parcel_latest"):
        payload["parcel_latest"] = context.get("parcel_latest")
    if context.get("global_edaphology"):
        payload["global_edaphology"] = context.get("global_edaphology")
    if profile:
        payload["profile"] = profile

    return payload


def _build_target_crop_payload(target_crop: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not target_crop:
        return None
    return {
        "user_crop_id": target_crop.get("id"),
        "crop_name": target_crop.get("crop_name"),
        "display_name": target_crop.get("display_name"),
        "growth_stage": target_crop.get("growth_stage"),
        "progress": target_crop.get("progress"),
        "expected_harvest_at": target_crop.get("expected_harvest_at"),
    }


async def respond(req: AgroBotRequest) -> AgroBotResponse:
    intent = detect_intent(req.message)
    warnings = []

    context = build_context(req.user_id, req.message)
    mode = _resolve_mode(req, intent, context)
    target_crop = _resolve_target_crop(context, intent, mode)

    if context.get("rag_conflict"):
        warnings.append("requested_crop_not_active")
    if not context.get("active_crops"):
        warnings.append("no_active_crops")

    profile = _select_profile(context, target_crop)
    health = _pick_health(context, target_crop)

    use_rag = should_query_rag(intent, mode) or context.get("rag_conflict") is True
    rag_payload: Optional[Dict[str, Any]] = None
    if use_rag:
        rag_payload = await query_rag_for_message(
            req.message,
            context,
            intent,
            mode=mode,
            profile=profile,
            health=health,
        )
        if rag_payload.get("error"):
            warnings.append("rag_error")
        if rag_payload.get("insufficient_evidence"):
            warnings.append(rag_payload.get("insufficient_reason") or "rag_insufficient")

    recommendation = await maybe_generate_recommendation(
        intent.intent,
        target_crop.get("id") if target_crop else None,
    )

    answer = compose_answer(
        intent=intent,
        context=context,
        profile=profile,
        health=health,
        recommendation=recommendation,
        rag=rag_payload,
        mode=mode,
    )

    return AgroBotResponse(
        answer=answer,
        mode=mode,
        intent=intent.intent,
        target_crop=_build_target_crop_payload(target_crop),
        context=_build_context_payload(context, target_crop, profile),
        health=health,
        recommendation=recommendation,
        rag=rag_payload,
        warnings=warnings,
    )
