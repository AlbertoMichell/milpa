from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class AgroBotRequest(BaseModel):
    user_id: int
    username: Optional[str] = None
    message: str
    source: str = "dashboard"
    mode: Literal["auto", "parcela", "biblioteca"] = "auto"


class AgroBotResponse(BaseModel):
    answer: str
    mode: str
    intent: str
    target_crop: Optional[Dict[str, Any]] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    health: Optional[Dict[str, Any]] = None
    recommendation: Optional[Dict[str, Any]] = None
    rag: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)
