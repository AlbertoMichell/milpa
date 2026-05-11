from __future__ import annotations

from typing import Any, Dict, Optional

from .schemas import AgroBotRequest, AgroBotResponse
from .intent import detect_intent, normalize_text
from .context_builder import build_context
from .composer import compose_answer
from .evidence import query_rag_for_message, should_query_rag
from .recommender_bridge import maybe_generate_recommendation


_SINGLE_CROP_FALLBACK_INTENTS = {
    "unknown",
    "crop_status",
    "harvest_date",
    "water_balance",
    "pest_or_disease",
    "fertilization",
    "soil_condition",
    "climate_risk",
}


def _select_profile(
    context: Dict[str, Any],
    target_crop: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not target_crop:
        return None
    profiles = context.get("profiles_by_name") or {}
    key = normalize_text(target_crop.get("crop_name"))
    return profiles.get(key)


def _pick_health(
    context: Dict[str, Any],
    target_crop: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not target_crop:
        return None

    crop_id = target_crop.get("id")
    index = context.get("health_index") or {}
    item = index.get(str(crop_id))
    if item:
        return item

    for candidate in context.get("health_by_crop") or []:
        if str(candidate.get("crop_id")) == str(crop_id):
            return candidate
    return None


def _resolve_target_crop(
    context: Dict[str, Any],
    intent_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Decide el cultivo objetivo real.

    El contexto solo marca cultivo explícito. El fallback se permite únicamente
    cuando hay UN solo cultivo activo, porque ahí no hay ambigüedad.
    """
    explicit = context.get("requested_active_crop")
    if explicit:
        context["target_crop"] = explicit
        context["target_crop_source"] = "explicit"
        return explicit

    active_crops = context.get("active_crops") or []
    fallback = context.get("fallback_crop")

    if len(active_crops) == 1 and fallback and intent_name in _SINGLE_CROP_FALLBACK_INTENTS:
        context["target_crop"] = fallback
        context["target_crop_source"] = "fallback_single_crop"
        return fallback

    context["target_crop"] = None
    context["target_crop_source"] = "none"
    return None


def _resolve_mode(
    req_mode: str,
    intent_is_library: bool,
    has_active_crops: bool,
) -> str:
    if req_mode != "auto":
        return req_mode
    if intent_is_library or not has_active_crops:
        return "biblioteca"
    return "parcela"


def _build_context_payload(
    context: Dict[str, Any],
    target_crop: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "active_crops_count": len(context.get("active_crops") or []),
        "target_crop_source": context.get("target_crop_source"),
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
    active_crops = context.get("active_crops") or []

    target_crop = _resolve_target_crop(context, intent.intent)
    profile = _select_profile(context, target_crop)
    health = _pick_health(context, target_crop)

    if context.get("rag_conflict"):
        warnings.append("requested_crop_not_active")
    if not active_crops:
        warnings.append("no_active_crops")
    if context.get("target_crop_source") == "none" and len(active_crops) > 1 and intent.intent != "water_balance":
        warnings.append("ambiguous_crop_context")

    mode = _resolve_mode(
        req_mode=req.mode,
        intent_is_library=intent.is_library,
        has_active_crops=bool(active_crops),
    )

    use_rag = should_query_rag(intent, mode) or context.get("rag_conflict") is True
    rag_payload: Optional[Dict[str, Any]] = None

    if use_rag:
        rag_payload = await query_rag_for_message(
            message=req.message,
            context=context,
            intent=intent,
            mode=mode,
            profile=profile,
            health=health,
        )
        if rag_payload.get("error"):
            warnings.append("rag_error")

    recommendation = None
    if mode == "parcela" and target_crop:
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
