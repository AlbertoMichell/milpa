from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from .diagnostics import crop_display_label, crop_status_line, sensor_summary, water_status
from .intent import IntentResult, normalize_text


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
    m = re.search(r"\n\s*Fuentes:\s*", text, flags=re.IGNORECASE)
    if m:
        text = text[: m.start()].strip()
    text = re.sub(r"^Pasos y recomendaciones para \"[^\"]+\"\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Hallazgos en la biblioteca para \"[^\"]+\"\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Parametros agronomicos relevantes para \"[^\"]+\"\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Informacion encontrada relacionada con \"[^\"]+\"\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^Definicion de \"[^\"]+\"\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip() if text else None


def _recommendation_line(recommendation: Optional[Dict[str, Any]]) -> Optional[str]:
    if not recommendation or not recommendation.get("action"):
        return None
    detail = _strip_html(recommendation.get("detail_html"))
    line = f"Recomendacion del sistema: {recommendation.get('action')}."
    if detail:
        line += f" {detail}"
    return line


def _health_line(health: Optional[Dict[str, Any]]) -> Optional[str]:
    if not health:
        return None
    label = health.get("label") or "sin evaluar"
    score = health.get("score")
    summary = health.get("summary") or ""
    if score is not None:
        return f"Salud general: {label} (score {score}). {summary}".strip()
    return f"Salud general: {label}. {summary}".strip()


def _profile_range_text(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return "sin perfil"
    lo = profile.get("optimal_soil_moisture_min")
    hi = profile.get("optimal_soil_moisture_max")
    if lo is None and hi is None:
        return "sin perfil"
    return f"{lo if lo is not None else '?'}-{hi if hi is not None else '?'}%"


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
            "No entendi tu mensaje. Prueba con el nombre de un cultivo activo o "
            "una consulta como 'como estoy de agua' o 'plagas en el maiz'."
        )

    active_crops = context.get("active_crops") or []
    target_crop = context.get("target_crop")
    rag_text = _extract_rag_answer(rag)

    if context.get("rag_conflict") and context.get("requested_crop_name"):
        label = context["requested_crop_name"]
        base = (
            f"Aviso: preguntaste por \"{label}\" pero no es un cultivo activo en tu parcela."
        )
        if rag_text:
            return f"{base}\n\n{rag_text}"
        return f"{base} Puedo responder desde biblioteca si lo deseas."

    if not active_crops:
        if rag_text:
            return rag_text
        return "Aun no tienes cultivos registrados. Agrega uno en Configuracion."

    if intent.intent == "library_question" and rag_text:
        return rag_text

    if intent.intent == "water_balance" and not target_crop and len(active_crops) > 1:
        lines = [f"Estado hidrico de tus {len(active_crops)} cultivos:"]
        profiles_by_name = context.get("profiles_by_name") or {}
        for crop in active_crops:
            label = crop_display_label(crop)
            soil = crop.get("soil_moisture")
            soil_text = f"{float(soil):.0f}%" if soil is not None else "?"
            profile_item = profiles_by_name.get(normalize_text(crop.get("crop_name")))
            range_text = _profile_range_text(profile_item)
            status = water_status(soil, profile_item)
            lines.append(
                f"- {label}: humedad suelo {soil_text} (rango {range_text}) -> {status}."
            )
        global_edaphology = context.get("global_edaphology") or {}
        if global_edaphology.get("precipitation") is not None:
            lines.append(
                f"\nPrecipitacion reciente: {float(global_edaphology['precipitation']):.1f} mm."
            )
        lines.append("\nRecomendacion: revisa cada cultivo si necesitas acciones concretas.")
        return "\n".join(lines)

    if target_crop:
        lines: List[str] = []
        lines.append(crop_status_line(target_crop))
        sensors = sensor_summary(target_crop)
        if sensors:
            lines.append(f"Sensores: {sensors}.")

        if intent.intent == "harvest_date":
            harvest_at = target_crop.get("expected_harvest_at")
            if harvest_at:
                lines.append(f"Cosecha estimada: {str(harvest_at)[:10]}.")
            else:
                lines.append("No hay fecha de cosecha estimada registrada.")

        health_line = _health_line(health)
        if health_line:
            lines.append(health_line)

        rec_line = _recommendation_line(recommendation)
        if rec_line:
            lines.append(rec_line)

        if rag_text and (mode == "biblioteca" or intent.intent in {"pest_or_disease", "fertilization", "soil_condition", "climate_risk"}):
            lines.append(rag_text)

        return "\n\n".join(line for line in lines if line)

    if rag_text:
        return rag_text

    crop_lines = [f"- {crop_status_line(c)}".strip() for c in active_crops]
    return "Tus cultivos activos:\n" + "\n".join(crop_lines) + "\n\nPuedes preguntar por uno en particular."
