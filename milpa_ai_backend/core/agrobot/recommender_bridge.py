from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from milpa_ai_backend.api.crops import RecommendationRequest, generate_recommendation
from milpa_ai_backend.core.logic.db import get_conn


_SKIP_INTENTS = {
    "water_balance",
    "library_question",
    "garbage",
    "harvest_date",
}


def _model_to_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return value.dict()
    return None


def get_recent_recommendation(
    user_crop_id: int,
    max_age_hours: int = 6,
) -> Optional[Dict[str, Any]]:
    """
    Evita que AgroBot genere una recomendación idéntica o equivalente por cada
    mensaje del usuario. La tabla actual no tiene columna `intent`, así que se
    reutiliza cualquier recomendación pendiente reciente del mismo cultivo.
    """
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, user_crop_id, query_text, action, priority, detail_html,
                       citations, status, faithfulness, created_at
                FROM recommendations
                WHERE user_crop_id = ?
                  AND status = 'pendiente'
                  AND created_at >= datetime('now', ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (int(user_crop_id), f"-{int(max_age_hours)} hours"),
            ).fetchone()
    except Exception:
        return None

    if not row:
        return None

    cols = [
        "id",
        "user_crop_id",
        "query_text",
        "action",
        "priority",
        "detail_html",
        "citations",
        "status",
        "faithfulness",
        "created_at",
    ]
    return dict(zip(cols, row))


async def maybe_generate_recommendation(
    intent_name: str,
    target_crop_id: Optional[int],
    max_age_hours: int = 6,
) -> Optional[Dict[str, Any]]:
    if not target_crop_id:
        return None
    if intent_name in _SKIP_INTENTS:
        return None

    recent = get_recent_recommendation(int(target_crop_id), max_age_hours=max_age_hours)
    if recent:
        recent["source"] = "recent_pending"
        return recent

    try:
        generated = await generate_recommendation(
            RecommendationRequest(user_crop_id=int(target_crop_id), force=False)
        )
        data = _model_to_dict(generated)
        if data:
            data["source"] = "generated"
        return data
    except HTTPException:
        return None
    except Exception:
        return None
