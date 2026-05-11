from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from milpa_ai_backend.api.crops import RecommendationRequest, generate_recommendation


_SKIP_INTENTS = {
    "water_balance",
    "library_question",
    "garbage",
    "harvest_date",
}


async def maybe_generate_recommendation(
    intent_name: str,
    target_crop_id: Optional[int],
) -> Optional[Dict[str, Any]]:
    if not target_crop_id:
        return None
    if intent_name in _SKIP_INTENTS:
        return None
    try:
        return await generate_recommendation(RecommendationRequest(user_crop_id=int(target_crop_id)))
    except HTTPException:
        return None
    except Exception:
        return None
