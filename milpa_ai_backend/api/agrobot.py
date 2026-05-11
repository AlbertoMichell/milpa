from __future__ import annotations

from fastapi import APIRouter, HTTPException

from milpa_ai_backend.core.agrobot.schemas import AgroBotRequest, AgroBotResponse
from milpa_ai_backend.core.agrobot.service import respond

router = APIRouter()


@router.post("/api/agrobot/respond", response_model=AgroBotResponse)
async def agrobot_respond(req: AgroBotRequest):
    try:
        return await respond(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AgroBot error: {exc}")
