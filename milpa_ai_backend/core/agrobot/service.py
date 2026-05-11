from __future__ import annotations

from typing import Any, Dict, Optional

from .schemas import AgroBotRequest, AgroBotResponse
from .intent import detect_intent, normalize_text
from .context_builder import build_context
from .composer import compose_answer
from .evidence import query_rag_for_message, should_query_rag
from .recommender_bridge import maybe_generate_recommendation


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


def _build_context_payload(context: Dict[str, Any], target_crop: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
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
    payload["active_crops_count"] = len(context.get("active_crops") or [])
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
    target_crop = context.get("target_crop")

    if context.get("rag_conflict"):
        warnings.append("requested_crop_not_active")
    if not context.get("active_crops"):
        warnings.append("no_active_crops")

    if req.mode != "auto":
        mode = req.mode
    elif intent.is_library or not context.get("active_crops"):
        mode = "biblioteca"
    else:
        mode = "parcela"

    use_rag = should_query_rag(intent, mode) or context.get("rag_conflict") is True
    rag_payload: Optional[Dict[str, Any]] = None
    if use_rag:
        rag_payload = await query_rag_for_message(req.message, context, intent)
        if rag_payload.get("error"):
            warnings.append("rag_error")

    recommendation = await maybe_generate_recommendation(intent.intent, target_crop.get("id") if target_crop else None)
    profile = _select_profile(context, target_crop)
    health = _pick_health(context, target_crop)

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
