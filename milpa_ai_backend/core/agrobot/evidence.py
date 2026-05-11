from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from milpa_ai_backend.api.rag import QueryRequest, query_rag
from .diagnostics import crop_display_label
from .intent import IntentResult, normalize_text


_RAG_INTENTS = {
    "library_question",
    "pest_or_disease",
    "fertilization",
    "soil_condition",
}

# Estos intents se resuelven con sensores/BD, no con RAG.
_SENSOR_ONLY_INTENTS = {
    "water_balance",
    "temperature_status",
    "wind_status",
    "precipitation_status",
    "air_humidity_status",
    "light_status",
    "climate_status",
}

_TECHNICAL_QUERY_BY_INTENT = {
    "pest_or_disease": "plagas enfermedades manejo sanitario control prevencion",
    "fertilization": "fertilizacion nutricion abonado requerimientos manejo",
    "soil_condition": "suelo pH conductividad salinidad humedad materia organica manejo",
}

_HISTORY_TERMS = {
    "historia", "origen", "originario", "originaria", "domesticacion", "domesticación",
    "prehispanico", "prehispánico", "ancestral", "mesoamerica", "mesoamérica", "teocintle",
}
_PROMPT_LEAK_TERMS = {
    "eres el componente documental", "agrobot milpa", "no debes desplazar",
    "salud calculada", "pregunta del agricultor", "devuelve solo manejo tecnico",
    "devuelve solo manejo técnico",
}
_GENERIC_BAD_TERMS = {
    "pasos y recomendaciones para «eres",
    "pasos y recomendaciones para \"eres",
    "parametros agronomicos relevantes para «recomendaciones",
    "parámetros agronómicos relevantes para «recomendaciones",
}


def should_query_rag(intent: IntentResult, mode: str) -> bool:
    if intent.is_garbage:
        return False
    if intent.intent in _SENSOR_ONLY_INTENTS:
        return False
    if mode == "biblioteca":
        return True
    return intent.intent in _RAG_INTENTS


def _crop_name(target_crop: Optional[Dict[str, Any]], context: Dict[str, Any]) -> Optional[str]:
    if target_crop and target_crop.get("crop_name"):
        return str(target_crop.get("crop_name"))
    if context.get("requested_crop_name"):
        return str(context.get("requested_crop_name"))
    return None


def _build_clean_query(message: str, context: Dict[str, Any], intent: IntentResult, mode: str) -> str:
    """
    El RAG del proyecto usa `query` para buscar y también como encabezado de síntesis.
    Por eso NUNCA se envían prompts largos ni sensores dentro de la query.
    """
    raw = str(message or "").strip()
    crop = _crop_name(context.get("target_crop"), context)

    if mode == "biblioteca":
        return raw or "consulta agricola de biblioteca"

    if intent.intent in _TECHNICAL_QUERY_BY_INTENT:
        topic = _TECHNICAL_QUERY_BY_INTENT[intent.intent]
        if crop:
            return f"{topic} en cultivo de {crop}: {raw}".strip()
        active_crops = context.get("active_crops") or []
        if active_crops:
            names = ", ".join(crop_display_label(crop_item) for crop_item in active_crops)
            return f"{topic} para cultivos activos ({names}): {raw}".strip()
        return f"{topic}: {raw}".strip()

    if context.get("rag_conflict") and crop:
        return raw or f"informacion tecnica sobre {crop}"
    return raw or "consulta agricola"


def _build_rag_params(context: Dict[str, Any], mode: str) -> Dict[str, Any]:
    if context.get("rag_conflict") and context.get("requested_crop_name"):
        return {"crop_focus": context["requested_crop_name"], "retrieval_scope": "crop_boost"}
    if mode == "biblioteca" and context.get("requested_crop_name"):
        return {"crop_focus": context["requested_crop_name"], "retrieval_scope": "crop_boost"}
    target = context.get("target_crop")
    if target:
        params: Dict[str, Any] = {"crop_focus": target.get("crop_name"), "retrieval_scope": "crop_boost"}
        if target.get("id") is not None:
            params["user_crop_id"] = int(target.get("id"))
        return params
    return {"retrieval_scope": "global"}


def _strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fragment_to_dict(fragment: Any) -> Dict[str, Any]:
    return {
        "doc_id": getattr(fragment, "doc_id", None),
        "doc_title": getattr(fragment, "doc_title", None),
        "text": getattr(fragment, "text", None),
        "page": getattr(fragment, "page", None),
        "score": getattr(fragment, "score", None),
    }


def _fragments_text(resp: Any) -> str:
    parts: List[str] = []
    for fragment in getattr(resp, "fragments", []) or []:
        item = _fragment_to_dict(fragment)
        if item.get("doc_title"):
            parts.append(str(item["doc_title"]))
        if item.get("text"):
            parts.append(str(item["text"]))
    return " ".join(parts)


def _contains_any(text: str, terms: set[str]) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in terms)


def _looks_like_prompt_leak(text: str) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in _PROMPT_LEAK_TERMS)


def _looks_like_generic_bad_answer(text: str) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in _GENERIC_BAD_TERMS)


def _is_history_query(message: str) -> bool:
    norm = normalize_text(message)
    return any(term in norm for term in {"historia", "origen", "origenes", "orígenes", "domesticacion", "domesticación"})


def _passes_quality_gate(message: str, intent: IntentResult, mode: str, resp: Any) -> tuple[bool, str]:
    answer = _strip_html(getattr(resp, "answer", "") or "")
    evidence_text = f"{answer} {_fragments_text(resp)}"
    if getattr(resp, "insufficient_evidence", False):
        return False, "rag_insufficient_evidence"
    if not answer:
        return False, "rag_empty_answer"
    if "no hay informacion suficiente" in normalize_text(answer):
        return False, "rag_declared_insufficient"
    if _looks_like_prompt_leak(answer):
        return False, "rag_prompt_leak"
    if _looks_like_generic_bad_answer(answer):
        return False, "rag_generic_or_unrelated_answer"
    if mode == "biblioteca" and _is_history_query(message):
        if not _contains_any(evidence_text, _HISTORY_TERMS):
            return False, "rag_no_history_support"
    return True, "ok"


async def query_rag_for_message(
    message: str,
    context: Dict[str, Any],
    intent: IntentResult,
    mode: str = "auto",
    profile: Optional[Dict[str, Any]] = None,
    health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    del profile, health  # sensores/perfil nunca se inyectan como prompt al RAG
    try:
        query = _build_clean_query(message=message, context=context, intent=intent, mode=mode)
        params = _build_rag_params(context, mode=mode)
        req = QueryRequest(query=query, k=8, mode="hybrid", **params)
        resp = await query_rag(req)
        ok, reason = _passes_quality_gate(message, intent, mode, resp)
        fragments = [_fragment_to_dict(fragment) for fragment in (getattr(resp, "fragments", []) or [])]
        return {
            "used": True,
            "query": query,
            "answer": resp.answer if ok else None,
            "raw_answer": resp.answer,
            "answer_mode": resp.answer_mode if ok else "insufficient",
            "insufficient_evidence": not ok,
            "insufficient_reason": None if ok else reason,
            "citations": (resp.citations or []) if ok else [],
            "fragments": fragments,
            "retrieval_scope": params.get("retrieval_scope", "global"),
            "crop_trace": resp.crop_trace,
            "intent": intent.intent,
            "role": "library_answer" if mode == "biblioteca" else "evidence_only",
        }
    except Exception as exc:
        return {
            "used": False,
            "error": str(exc),
            "intent": intent.intent,
            "insufficient_evidence": True,
            "insufficient_reason": "rag_exception",
        }
