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
    "climate_risk",
}

_TECHNICAL_QUERY_BY_INTENT = {
    "pest_or_disease": "plagas enfermedades manejo sanitario control prevención",
    "fertilization": "fertilización nutrición abonado requerimientos manejo",
    "soil_condition": "suelo pH conductividad salinidad humedad materia orgánica manejo",
    "climate_risk": "clima temperatura lluvia sequía helada viento riesgo manejo",
}

_HISTORY_TERMS = {
    "historia",
    "origen",
    "originario",
    "originaria",
    "domesticacion",
    "domesticación",
    "prehispanico",
    "prehispánico",
    "ancestral",
    "mesoamerica",
    "mesoamérica",
    "teocintle",
}

_PROMPT_LEAK_TERMS = {
    "eres el componente documental",
    "agrobot milpa",
    "no debes desplazar",
    "salud calculada",
    "pregunta del agricultor",
    "devuelve solo manejo técnico",
}

_GENERIC_BAD_TERMS = {
    "beneficios de la rotacion",
    "beneficios de la rotación",
    "cultivo de cobertura",
    "seccion 12",
    "sección 12",
    "pasos y recomendaciones para «eres",
    "pasos y recomendaciones para \"eres",
    "parametros agronomicos relevantes para «recomendaciones",
    "parámetros agronómicos relevantes para «recomendaciones",
}


def should_query_rag(intent: IntentResult, mode: str) -> bool:
    if intent.is_garbage:
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


def _build_clean_query(
    message: str,
    context: Dict[str, Any],
    intent: IntentResult,
    mode: str,
) -> str:
    """
    IMPORTANTE:
    El RAG de este proyecto usa `query` no solo para buscar, sino también como
    encabezado de síntesis. Por eso NUNCA se deben mandar prompts largos tipo
    "Eres el componente...". Aquí solo se envían consultas limpias y cortas.
    """
    raw = str(message or "").strip()
    target_crop = context.get("target_crop")
    crop = _crop_name(target_crop, context)

    if mode == "biblioteca":
        return raw or "consulta agrícola de biblioteca"

    if intent.intent in _TECHNICAL_QUERY_BY_INTENT:
        topic = _TECHNICAL_QUERY_BY_INTENT[intent.intent]
        if crop:
            return f"{topic} en cultivo de {crop}: {raw}".strip()
        active_crops = context.get("active_crops") or []
        if active_crops:
            names = ", ".join(crop_display_label(crop_item) for crop_item in active_crops)
            return f"{topic} para cultivos activos ({names}): {raw}".strip()
        return f"{topic}: {raw}".strip()

    # Conflicto: cultivo no activo. Se permite buscar biblioteca, pero sin diagnóstico.
    if context.get("rag_conflict") and crop:
        return raw or f"información técnica sobre {crop}"

    return raw or "consulta agrícola"


def _build_rag_params(context: Dict[str, Any], mode: str) -> Dict[str, Any]:
    if context.get("rag_conflict") and context.get("requested_crop_name"):
        return {
            "crop_focus": context["requested_crop_name"],
            "retrieval_scope": "crop_boost",
        }

    if mode == "biblioteca" and context.get("requested_crop_name"):
        return {
            "crop_focus": context["requested_crop_name"],
            "retrieval_scope": "crop_boost",
        }

    target = context.get("target_crop")
    if target:
        params: Dict[str, Any] = {
            "crop_focus": target.get("crop_name"),
            "retrieval_scope": "crop_boost",
        }
        if target.get("id") is not None:
            params["user_crop_id"] = int(target.get("id"))
        return params

    return {"retrieval_scope": "global"}


def _strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fragments_text(resp: Any) -> str:
    parts: List[str] = []
    for fragment in getattr(resp, "fragments", []) or []:
        text = getattr(fragment, "text", "") or ""
        title = getattr(fragment, "doc_title", "") or ""
        if title:
            parts.append(str(title))
        if text:
            parts.append(str(text))
    return " ".join(parts)


def _contains_any(text: str, terms: set[str]) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in terms)


def _looks_like_prompt_leak(text: str) -> bool:
    norm = normalize_text(text)
    return any(term in norm for term in _PROMPT_LEAK_TERMS)


def _looks_like_generic_bad_answer(text: str) -> bool:
    norm = normalize_text(text)
    return any(normalize_text(term) in norm for term in _GENERIC_BAD_TERMS)


def _is_history_query(message: str) -> bool:
    norm = normalize_text(message)
    return any(term in norm for term in {"historia", "origen", "origenes", "orígenes"})


def _passes_quality_gate(message: str, intent: IntentResult, mode: str, resp: Any) -> tuple[bool, str]:
    answer = _strip_html(getattr(resp, "answer", "") or "")
    evidence_text = f"{answer} {_fragments_text(resp)}"

    if getattr(resp, "insufficient_evidence", False):
        return False, "rag_insufficient_evidence"

    if not answer:
        return False, "rag_empty_answer"

    if "no hay información suficiente" in normalize_text(answer):
        return False, "rag_declared_insufficient"

    if _looks_like_prompt_leak(answer):
        return False, "rag_prompt_leak"

    if _looks_like_generic_bad_answer(answer):
        return False, "rag_generic_or_unrelated_answer"

    # Si preguntan historia/origen, no aceptamos fragmentos de manejo, rotación o cobertura.
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
    del profile, health  # El RAG no recibe sensores/perfil como prompt; solo evidencia documental.

    try:
        query = _build_clean_query(
            message=message,
            context=context,
            intent=intent,
            mode=mode,
        )
        params = _build_rag_params(context, mode=mode)

        req = QueryRequest(query=query, k=8, mode="hybrid", **params)
        resp = await query_rag(req)

        ok, reason = _passes_quality_gate(message, intent, mode, resp)

        return {
            "used": True,
            "query": query,
            "answer": resp.answer if ok else None,
            "answer_mode": resp.answer_mode if ok else "insufficient",
            "insufficient_evidence": not ok,
            "insufficient_reason": None if ok else reason,
            "citations": resp.citations or [] if ok else [],
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
