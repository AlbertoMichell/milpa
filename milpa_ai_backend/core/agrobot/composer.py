from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from .diagnostics import (
    build_action_hint,
    crop_display_label,
    crop_status_line,
    explain_health,
    profile_comparison,
    range_text,
    sensor_summary,
    water_status,
    profile_range,
)
from .intent import IntentResult, normalize_text


_TECHNICAL_RAG_INTENTS = {
    "pest_or_disease",
    "fertilization",
    "soil_condition",
    "climate_risk",
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


def _extract_rag_answer(rag: Optional[Dict[str, Any]]) -> Optional[str]:
    if not rag or not rag.get("answer"):
        return None
    if rag.get("insufficient_evidence") is True or rag.get("answer_mode") == "insufficient":
        return None

    text = _strip_html(rag.get("answer"))
    if not text:
        return None

    m = re.search(r"\n\s*Fuentes:\s*", text, flags=re.IGNORECASE)
    if m:
        text = text[: m.start()].strip()

    # Limpieza mínima. No usamos la limpieza agresiva vieja del frontend.
    text = re.sub(r"^Pasos y recomendaciones para [\"«][^\"»]+[\"»]\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Hallazgos en la biblioteca para [\"«][^\"»]+[\"»]\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Par[aá]metros agron[oó]micos relevantes para [\"«][^\"»]+[\"»]\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Informaci[oó]n encontrada relacionada con [\"«][^\"»]+[\"»]\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Definici[oó]n de [\"«][^\"»]+[\"»]\s*:\s*", "", text, flags=re.IGNORECASE)

    text = text.strip()
    if len(text) > 1100:
        text = text[:1100].rsplit(" ", 1)[0] + "..."
    return text or None


def _recommendation_text(recommendation: Optional[Dict[str, Any]]) -> Optional[str]:
    if not recommendation or not recommendation.get("action"):
        return None

    action = str(recommendation.get("action") or "").strip()
    priority = str(recommendation.get("priority") or "").strip()
    detail = _strip_html(recommendation.get("detail_html"))
    source = recommendation.get("source")

    parts = []
    if priority:
        parts.append(f"prioridad {priority}")
    if source == "recent_pending":
        parts.append("recomendación pendiente reciente")

    suffix = f" ({', '.join(parts)})" if parts else ""
    line = f"{action}{suffix}."

    if detail:
        if len(detail) > 500:
            detail = detail[:500].rsplit(" ", 1)[0] + "..."
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

    if rag_text and (mode == "biblioteca" or intent.intent in _TECHNICAL_RAG_INTENTS):
        sections.append("Soporte de biblioteca:\n" + rag_text)

    return "\n\n".join(s for s in sections if s and s.strip())


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
            "o una consulta como 'cómo estoy de agua' o 'plagas en el maíz'."
        )

    active_crops = context.get("active_crops") or []
    target_crop = context.get("target_crop")
    rag_text = _extract_rag_answer(rag)

    if context.get("rag_conflict") and context.get("requested_crop_name"):
        label = context["requested_crop_name"]
        base = f"Aviso: preguntaste por '{label}', pero no es un cultivo activo en tu parcela."
        if rag_text:
            return f"{base}\n\nInformación de biblioteca:\n{rag_text}"
        return f"{base} Puedo responder desde biblioteca, pero no puedo hacer diagnóstico personalizado sin un cultivo activo."

    if not active_crops:
        if rag_text:
            return rag_text
        return "Aún no tienes cultivos registrados. Agrega uno en Configuración para recibir diagnóstico de parcela."

    if mode == "biblioteca":
        if rag_text:
            return rag_text
        return "No encontré evidencia suficiente en la biblioteca para responder esa consulta."

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
            mode=mode,
        )

    crop_lines = [f"- {crop_status_line(c)}".strip() for c in active_crops]
    return (
        "Tienes varios cultivos activos y no detecté uno específico en tu pregunta.\n\n"
        + "Cultivos activos:\n"
        + "\n".join(crop_lines)
        + "\n\nPregunta por uno en particular, por ejemplo: '¿cómo va mi maíz?' o 'plagas en mi frijol'."
    )
