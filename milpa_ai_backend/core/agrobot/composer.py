from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .diagnostics import (
    build_action_hint,
    crop_display_label,
    crop_status_line,
    explain_health,
    profile_comparison,
    profile_range,
    range_text,
    sensor_summary,
    water_status,
)
from .intent import IntentResult, normalize_text


_TECHNICAL_RAG_INTENTS = {
    "pest_or_disease",
    "fertilization",
    "soil_condition",
    "climate_risk",
}

_DIRTY_TEXT_MARKERS = {
    "eres el componente documental",
    "tu respuesta será usada solo como evidencia",
    "tu respuesta sera usada solo como evidencia",
    "no debes desplazar ni contradecir",
    "pregunta del agricultor",
    "devuelve solo manejo técnico",
    "devuelve solo manejo tecnico",
    "parámetros agronómicos relevantes para «recomendaciones",
    "parametros agronomicos relevantes para «recomendaciones",
    "pasos y recomendaciones para «eres",
    "pasos y recomendaciones para \"eres",
}

_BAD_GENERIC_MARKERS = {
    "beneficios de la rotación",
    "beneficios de la rotacion",
    "cultivo de cobertura",
    "sección 12",
    "seccion 12",
}


def _strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    out = str(text)
    out = re.sub(r"<br\s*/?>", "\n", out, flags=re.IGNORECASE)
    out = re.sub(r"</p>", "\n\n", out, flags=re.IGNORECASE)
    out = re.sub(r"<li>", "- ", out, flags=re.IGNORECASE)
    out = re.sub(r"</li>", "\n", out, flags=re.IGNORECASE)
    out = re.sub(r"<[^>]+>", "", out)
    out = out.replace("&nbsp;", " ").replace("&amp;", "&")
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _is_dirty_text(text: Optional[str]) -> bool:
    norm = normalize_text(text or "")
    if not norm:
        return False
    return any(normalize_text(marker) in norm for marker in _DIRTY_TEXT_MARKERS)


def _is_generic_bad_text(text: Optional[str]) -> bool:
    norm = normalize_text(text or "")
    if not norm:
        return False
    return any(normalize_text(marker) in norm for marker in _BAD_GENERIC_MARKERS)


def _remove_rag_heading(text: str) -> str:
    patterns = [
        r"^Pasos y recomendaciones para [\"«][^\"»]+[\"»]\s*:\s*",
        r"^Hallazgos en la biblioteca para [\"«][^\"»]+[\"»]\s*:\s*",
        r"^Par[aá]metros agron[oó]micos relevantes para [\"«][^\"»]+[\"»]\s*:\s*",
        r"^Informaci[oó]n encontrada relacionada con [\"«][^\"»]+[\"»]\s*:\s*",
        r"^Definici[oó]n de [\"«][^\"»]+[\"»]\s*:\s*",
    ]
    out = text.strip()
    for pattern in patterns:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE | re.DOTALL).strip()
    return out


def _extract_rag_answer(rag: Optional[Dict[str, Any]]) -> Optional[str]:
    if not rag or not rag.get("answer"):
        return None
    if rag.get("insufficient_evidence") is True or rag.get("answer_mode") == "insufficient":
        return None

    text = _strip_html(rag.get("answer"))
    if not text:
        return None

    if _is_dirty_text(text) or _is_generic_bad_text(text):
        return None

    if "no hay información suficiente" in normalize_text(text):
        return None

    marker = re.search(r"\n\s*Fuentes:\s*", text, flags=re.IGNORECASE)
    if marker:
        text = text[: marker.start()].strip()

    text = _remove_rag_heading(text)
    if _is_dirty_text(text) or _is_generic_bad_text(text):
        return None

    if len(text) > 1100:
        text = text[:1100].rsplit(" ", 1)[0] + "..."

    return text or None


def _clean_recommendation_detail(text: Optional[str]) -> str:
    detail = _strip_html(text)
    if not detail:
        return ""
    if _is_dirty_text(detail) or _is_generic_bad_text(detail):
        return ""
    if "no hay información suficiente" in normalize_text(detail):
        return ""

    detail = _remove_rag_heading(detail)
    if _is_dirty_text(detail) or _is_generic_bad_text(detail):
        return ""

    # Evita pegar fragmentos crudos excesivos dentro del chat.
    if len(detail) > 280:
        detail = detail[:280].rsplit(" ", 1)[0] + "..."
    return detail.strip()


def _recommendation_text(recommendation: Optional[Dict[str, Any]]) -> Optional[str]:
    if not recommendation or not recommendation.get("action"):
        return None

    action = str(recommendation.get("action") or "").strip()
    priority = str(recommendation.get("priority") or "").strip()
    source = recommendation.get("source")
    detail = _clean_recommendation_detail(recommendation.get("detail_html"))

    parts: List[str] = []
    if priority:
        parts.append(f"prioridad {priority}")
    if source == "recent_pending":
        parts.append("recomendación pendiente reciente")

    suffix = f" ({', '.join(parts)})" if parts else ""
    line = f"{action}{suffix}."
    if detail:
        line += f" {detail}"
    return line


def _profile_range_text(profile: Optional[Dict[str, Any]]) -> str:
    lo, hi = profile_range(profile)
    return range_text(lo, hi, "%")


def _compose_water_multicrop(context: Dict[str, Any]) -> str:
    active_crops = context.get("active_crops") or []
    profiles_by_name = context.get("profiles_by_name") or {}

    if not active_crops:
        return "No hay cultivos activos para evaluar el estado hídrico."

    low: List[str] = []
    high: List[str] = []
    ok: List[str] = []
    missing: List[str] = []

    lines = [f"Estado hídrico de tus {len(active_crops)} cultivo(s):"]

    for crop in active_crops:
        label = crop_display_label(crop)
        soil = crop.get("soil_moisture")
        soil_text = f"{float(soil):.0f}%" if soil is not None else "sin dato"
        profile_item = profiles_by_name.get(normalize_text(crop.get("crop_name")))
        range_txt = _profile_range_text(profile_item)
        status = water_status(soil, profile_item)

        lines.append(f"- {label}: humedad del suelo {soil_text} / rango {range_txt} -> {status}.")

        if status == "baja":
            low.append(label)
        elif status == "alta":
            high.append(label)
        elif status == "adecuada":
            ok.append(label)
        else:
            missing.append(label)

    global_edaphology = context.get("global_edaphology") or {}
    if global_edaphology.get("precipitation") is not None:
        try:
            lines.append(f"\nPrecipitación reciente: {float(global_edaphology['precipitation']):.1f} mm.")
        except (TypeError, ValueError):
            pass

    actions: List[str] = []
    if low:
        actions.append("prioriza riego en " + ", ".join(low))
    if high:
        actions.append("evita regar temporalmente " + ", ".join(high) + " y revisa drenaje")
    if ok:
        actions.append("mantén monitoreo en " + ", ".join(ok))
    if missing:
        actions.append("registra nueva lectura para " + ", ".join(missing))

    if actions:
        lines.append("\nRecomendación: " + "; ".join(actions) + ".")
    else:
        lines.append("\nRecomendación: registra nuevas lecturas antes de tomar una decisión de riego.")

    return "\n".join(lines)


def _compose_crop_answer(
    intent: IntentResult,
    target_crop: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    health: Optional[Dict[str, Any]],
    recommendation: Optional[Dict[str, Any]],
    rag_text: Optional[str],
    rag: Optional[Dict[str, Any]],
    mode: str,
) -> str:
    sections: List[str] = []

    sections.append(crop_status_line(target_crop))

    sensors = sensor_summary(target_crop)
    if sensors:
        sections.append(f"Sensores actuales: {sensors}.")
    else:
        sections.append("Sensores actuales: no hay lecturas recientes suficientes para este cultivo.")

    comparisons = profile_comparison(target_crop, profile)
    if comparisons:
        sections.append("Comparación contra perfil ideal:\n" + "\n".join(f"- {line}" for line in comparisons))

    health_lines = explain_health(health)
    if health_lines:
        sections.append("Diagnóstico:\n" + "\n".join(f"- {line}" for line in health_lines))

    if intent.intent == "harvest_date":
        harvest_at = target_crop.get("expected_harvest_at")
        if harvest_at:
            sections.append(f"Cosecha estimada: {str(harvest_at)[:10]}.")
        else:
            sections.append("Cosecha estimada: no hay fecha registrada para este cultivo.")

    rec = _recommendation_text(recommendation)
    action_hint = build_action_hint(
        intent_name=intent.intent,
        crop=target_crop,
        profile=profile,
        health=health,
        recommendation=recommendation,
    )

    if rec:
        sections.append("Recomendación:\n" + rec)
    elif action_hint:
        sections.append("Recomendación:\n" + action_hint)

    if intent.intent in _TECHNICAL_RAG_INTENTS:
        if rag_text:
            sections.append("Soporte de biblioteca:\n" + rag_text)
        elif rag and rag.get("used"):
            sections.append("Soporte de biblioteca:\nNo encontré información suficiente en los documentos para respaldar esa parte de la consulta.")

    return "\n\n".join(section for section in sections if section and section.strip())


def compose_answer(
    intent: IntentResult,
    context: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    health: Optional[Dict[str, Any]],
    recommendation: Optional[Dict[str, Any]],
    rag: Optional[Dict[str, Any]],
    mode: str,
) -> str:
    if intent.intent == "garbage":
        return (
            "No entendí tu mensaje. Prueba con el nombre de un cultivo activo "
            "o una consulta como '¿cómo estoy de agua?' o 'plagas en el maíz'."
        )

    active_crops = context.get("active_crops") or []
    target_crop = context.get("target_crop")
    rag_text = _extract_rag_answer(rag)

    if context.get("rag_conflict") and context.get("requested_crop_name") and mode != "biblioteca":
        label = context["requested_crop_name"]
        base = f"Aviso: preguntaste por '{label}', pero no es un cultivo activo en tu parcela."
        if rag_text:
            return f"{base}\n\nInformación de biblioteca:\n{rag_text}"
        return f"{base} No puedo hacer diagnóstico personalizado y no encontré información suficiente en la biblioteca para esa solicitud."

    if mode == "biblioteca":
        if rag_text:
            return rag_text
        return "No tengo información suficiente en la biblioteca para procesar esa solicitud."

    if not active_crops:
        return "Aún no tienes cultivos registrados. Agrega uno en Configuración para recibir diagnóstico de parcela."

    if intent.intent == "water_balance" and not target_crop:
        return _compose_water_multicrop(context)

    if target_crop:
        return _compose_crop_answer(
            intent=intent,
            target_crop=target_crop,
            profile=profile,
            health=health,
            recommendation=recommendation,
            rag_text=rag_text,
            rag=rag,
            mode=mode,
        )

    crop_lines = [f"- {crop_status_line(c)}".strip() for c in active_crops]
    return (
        "Tienes varios cultivos activos y no detecté uno específico en tu pregunta.\n\n"
        + "Cultivos activos:\n"
        + "\n".join(crop_lines)
        + "\n\nPregunta por uno en particular, por ejemplo: '¿cómo va mi maíz?' o 'plagas en mi frijol'."
    )
