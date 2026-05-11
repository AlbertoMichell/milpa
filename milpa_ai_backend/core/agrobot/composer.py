from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .diagnostics import (
    build_action_hint,
    crop_display_label,
    crop_metric_status_line,
    crop_status_line,
    explain_health,
    metric_value_from_context,
    precipitation_status,
    profile_comparison,
    profile_range,
    range_text,
    sensor_summary,
    water_status,
    wind_status,
)
from .intent import IntentResult, normalize_text


_TECHNICAL_RAG_INTENTS = {"pest_or_disease", "fertilization", "soil_condition"}
_PARCEL_METRIC_INTENTS = {
    "temperature_status",
    "wind_status",
    "precipitation_status",
    "air_humidity_status",
    "light_status",
    "climate_status",
    "soil_condition",
}

_DIRTY_TEXT_MARKERS = {
    "eres el componente documental",
    "tu respuesta sera usada solo como evidencia",
    "tu respuesta será usada solo como evidencia",
    "no debes desplazar ni contradecir",
    "pregunta del agricultor",
    "devuelve solo manejo tecnico",
    "devuelve solo manejo técnico",
    "parametros agronomicos relevantes para «recomendaciones",
    "parámetros agronómicos relevantes para «recomendaciones",
    "pasos y recomendaciones para «eres",
    "pasos y recomendaciones para \"eres",
}

_GENERIC_BAD_MARKERS = {
    "beneficios de la rotacion",
    "beneficios de la rotación",
    "cultivo de cobertura",
    "seccion 12",
    "sección 12",
    "tabla stream",
}

_HISTORY_TERMS = {
    "historia", "origen", "originario", "originaria", "mesoamerica", "mesoamérica",
    "domesticacion", "domesticación", "teocintle", "prehispanico", "prehispánico",
}


def _strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    out = str(text)
    out = re.sub(r"<br\s*/?>", "\n", out, flags=re.IGNORECASE)
    out = re.sub(r"</p>", "\n\n", out, flags=re.IGNORECASE)
    out = re.sub(r"<li[^>]*>", "- ", out, flags=re.IGNORECASE)
    out = re.sub(r"</li>", "\n", out, flags=re.IGNORECASE)
    out = re.sub(r"<[^>]+>", "", out)
    out = out.replace("&nbsp;", " ").replace("&amp;", "&")
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _is_dirty_text(text: Optional[str]) -> bool:
    norm = normalize_text(text or "")
    return bool(norm and any(normalize_text(marker) in norm for marker in _DIRTY_TEXT_MARKERS))


def _is_generic_bad_text(text: Optional[str]) -> bool:
    norm = normalize_text(text or "")
    return bool(norm and any(normalize_text(marker) in norm for marker in _GENERIC_BAD_MARKERS))


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


def _split_sentences(text: str) -> List[str]:
    text = re.sub(r"\[[0-9]+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    candidates = re.split(r"(?<=[.!?])\s+|\s+-\s+", text)
    return [c.strip(" -•\t\n") for c in candidates if len(c.strip()) > 20]


def _fragment_text(rag: Optional[Dict[str, Any]]) -> str:
    if not rag:
        return ""
    parts: List[str] = []
    raw_answer = rag.get("answer") or rag.get("raw_answer")
    if raw_answer:
        parts.append(_strip_html(raw_answer))
    for frag in rag.get("fragments") or []:
        if isinstance(frag, dict):
            title = frag.get("doc_title")
            text = frag.get("text")
            if title:
                parts.append(str(title))
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _clean_library_answer(message: str, rag: Optional[Dict[str, Any]]) -> Optional[str]:
    if not rag:
        return None
    if rag.get("insufficient_evidence") is True or rag.get("answer_mode") == "insufficient":
        return None

    raw = _fragment_text(rag)
    raw = _strip_html(raw)
    if not raw or _is_dirty_text(raw):
        return None

    marker = re.search(r"\n\s*Fuentes:\s*", raw, flags=re.IGNORECASE)
    if marker:
        raw = raw[: marker.start()].strip()
    raw = _remove_rag_heading(raw)
    raw = re.sub(r"={4,}|-{4,}", " ", raw)
    raw = re.sub(r"GU[IÍ]A COMPLETA DE CULTIVOS PARA EVALUACI[OÓ]N DEL SISTEMA RAG", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"SECCI[OÓ]N\s+\d+\s*:?\s*", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"CARACTER[IÍ]STICAS DEL MA[IÍ]Z", " ", raw, flags=re.IGNORECASE)

    norm_msg = normalize_text(message)
    sentences = _split_sentences(raw)

    if any(term in norm_msg for term in {"historia", "origen", "origenes", "domesticacion", "domesticación"}):
        selected: List[str] = []
        for sentence in sentences:
            ns = normalize_text(sentence)
            if any(normalize_text(term) in ns for term in _HISTORY_TERMS) or "zea mays" in ns:
                if not _is_generic_bad_text(sentence):
                    selected.append(sentence)
            if len(selected) >= 4:
                break
        if not selected:
            return None
        # Evitar salida tipo buscador: convertir a párrafo breve.
        answer = " ".join(selected)
        answer = re.sub(r"\s+", " ", answer).strip()
        if len(answer) > 900:
            answer = answer[:900].rsplit(" ", 1)[0] + "..."
        return answer

    # Para biblioteca general: quitar títulos crudos y devolver frases útiles.
    selected = [s for s in sentences if not _is_generic_bad_text(s) and not re.match(r"^[A-ZÁÉÍÓÚÑ0-9\s:_-]{20,}$", s)]
    if not selected:
        return None
    answer = " ".join(selected[:5])
    answer = re.sub(r"\s+", " ", answer).strip()
    if len(answer) > 1000:
        answer = answer[:1000].rsplit(" ", 1)[0] + "..."
    return answer


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
    if "no hay informacion suficiente" in normalize_text(text):
        return None
    marker = re.search(r"\n\s*Fuentes:\s*", text, flags=re.IGNORECASE)
    if marker:
        text = text[: marker.start()].strip()
    text = _remove_rag_heading(text)
    if _is_dirty_text(text) or _is_generic_bad_text(text):
        return None
    if len(text) > 900:
        text = text[:900].rsplit(" ", 1)[0] + "..."
    return text or None


def _clean_recommendation_detail(text: Optional[str]) -> str:
    detail = _strip_html(text)
    if not detail:
        return ""
    if _is_dirty_text(detail) or _is_generic_bad_text(detail):
        return ""
    if "no hay informacion suficiente" in normalize_text(detail):
        return ""
    detail = _remove_rag_heading(detail)
    if _is_dirty_text(detail) or _is_generic_bad_text(detail):
        return ""
    if len(detail) > 240:
        detail = detail[:240].rsplit(" ", 1)[0] + "..."
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


def _compose_temperature_multicrop(context: Dict[str, Any]) -> str:
    active_crops = context.get("active_crops") or []
    profiles_by_name = context.get("profiles_by_name") or {}
    current = metric_value_from_context(context, "air_temp")
    lines = []
    if current is not None:
        lines.append(f"Temperatura actual de la parcela: {current:.0f} °C.")
    else:
        lines.append("No tengo una lectura de temperatura reciente para la parcela.")
    if active_crops:
        lines.append("\nComparación por cultivo:")
        for crop in active_crops:
            profile = profiles_by_name.get(normalize_text(crop.get("crop_name")))
            lines.append(crop_metric_status_line(crop, profile, "air_temp"))
    lines.append("\nRecomendación: mantén monitoreo; si la temperatura sube por encima del rango de algún cultivo, evita labores de alto estrés en horas de calor.")
    return "\n".join(lines)


def _compose_wind(context: Dict[str, Any]) -> str:
    value = metric_value_from_context(context, "wind_speed")
    if value is None:
        return "No tengo una lectura reciente de viento para la parcela."
    status = wind_status(value)
    lines = [f"Viento actual de la parcela: {value:.1f} km/h -> {status}."]
    if status == "alto":
        lines.append("Recomendación: evita aplicaciones foliares, revisa tutores y protege estructuras sensibles.")
    elif status == "moderado":
        lines.append("Recomendación: mantén monitoreo y evita aplicaciones finas si hay rachas.")
    else:
        lines.append("Recomendación: condición normal; no representa riesgo fuerte en este momento.")
    return "\n\n".join(lines)


def _compose_precipitation(context: Dict[str, Any]) -> str:
    value = metric_value_from_context(context, "precipitation")
    if value is None:
        return "No tengo una lectura reciente de precipitación para la parcela."
    status = precipitation_status(value)
    lines = [f"Precipitación reciente: {value:.1f} mm -> {status}."]
    if value <= 0:
        lines.append("Recomendación: no hay lluvia reciente; decide riego con base en humedad del suelo por cultivo.")
    elif value < 20:
        lines.append("Recomendación: revisa humedad del suelo antes de volver a regar.")
    else:
        lines.append("Recomendación: revisa drenaje, encharcamientos y síntomas de enfermedades favorecidas por humedad alta.")
    return "\n\n".join(lines)


def _compose_air_humidity(context: Dict[str, Any]) -> str:
    active_crops = context.get("active_crops") or []
    profiles_by_name = context.get("profiles_by_name") or {}
    current = metric_value_from_context(context, "air_humidity")
    lines = []
    if current is not None:
        lines.append(f"Humedad relativa actual de la parcela: {current:.0f}%.")
    else:
        lines.append("No tengo una lectura reciente de humedad ambiental para la parcela.")
    if active_crops:
        lines.append("\nComparación por cultivo:")
        for crop in active_crops:
            profile = profiles_by_name.get(normalize_text(crop.get("crop_name")))
            lines.append(crop_metric_status_line(crop, profile, "air_humidity"))
    lines.append("\nRecomendación: si la humedad ambiental se mantiene alta, vigila hongos y ventilación; si baja demasiado, revisa estrés hídrico junto con humedad del suelo.")
    return "\n".join(lines)


def _compose_light(context: Dict[str, Any]) -> str:
    active_crops = context.get("active_crops") or []
    current = metric_value_from_context(context, "light")
    lines = []
    if current is not None:
        lines.append(f"Luz actual estimada de la parcela: {current:.0f}%.")
    else:
        lines.append("No tengo una lectura reciente de luz para la parcela.")
    if active_crops:
        lines.append("\nLectura por cultivo:")
        for crop in active_crops:
            lines.append(crop_metric_status_line(crop, None, "light"))
    lines.append("\nRecomendación: valida sombra, cobertura o exposición si notas crecimiento débil o estrés por radiación.")
    return "\n".join(lines)


def _compose_soil_condition(context: Dict[str, Any], target_crop: Optional[Dict[str, Any]] = None, profile: Optional[Dict[str, Any]] = None) -> str:
    global_edaphology = context.get("global_edaphology") or {}
    ph = global_edaphology.get("ph")
    conductivity = global_edaphology.get("conductivity")
    soil_temp = global_edaphology.get("soil_temp")
    lines = ["Condición edafológica disponible:"]
    if ph is not None:
        lines.append(f"- pH global: {float(ph):.2f}.")
    else:
        lines.append("- pH global: sin dato.")
    if conductivity is not None:
        lines.append(f"- Conductividad: {float(conductivity):.2f} dS/m.")
    else:
        lines.append("- Conductividad: sin dato.")
    if soil_temp is not None:
        lines.append(f"- Temperatura del suelo: {float(soil_temp):.0f} °C.")
    if target_crop:
        lines.append("\nComparación con cultivo objetivo:")
        lines.append(crop_metric_status_line(target_crop, profile, "ph", global_edaphology))
        lines.append(crop_metric_status_line(target_crop, profile, "conductivity", global_edaphology))
    else:
        active_crops = context.get("active_crops") or []
        profiles_by_name = context.get("profiles_by_name") or {}
        if active_crops:
            lines.append("\nComparación general por cultivo:")
            for crop in active_crops:
                p = profiles_by_name.get(normalize_text(crop.get("crop_name")))
                lines.append(crop_metric_status_line(crop, p, "ph", global_edaphology))
    if not context.get("nutrients_by_crop_id"):
        lines.append("\nNota: no hay nutrientes reales cargados para confirmar nitrógeno, fósforo, potasio o materia orgánica.")
    return "\n".join(lines)


def _compose_climate(context: Dict[str, Any]) -> str:
    temp = metric_value_from_context(context, "air_temp")
    hum = metric_value_from_context(context, "air_humidity")
    rain = metric_value_from_context(context, "precipitation")
    wind = metric_value_from_context(context, "wind_speed")
    parts = []
    if temp is not None:
        parts.append(f"temperatura {temp:.0f} °C")
    if hum is not None:
        parts.append(f"humedad relativa {hum:.0f}%")
    if rain is not None:
        parts.append(f"precipitación {rain:.1f} mm")
    if wind is not None:
        parts.append(f"viento {wind:.1f} km/h")
    if not parts:
        return "No tengo lecturas climáticas recientes para la parcela."
    lines = ["Condición climática actual: " + ", ".join(parts) + "."]
    lines.append("\nResumen por cultivo:")
    active_crops = context.get("active_crops") or []
    profiles_by_name = context.get("profiles_by_name") or {}
    alerts: List[str] = []
    for crop in active_crops:
        profile = profiles_by_name.get(normalize_text(crop.get("crop_name")))
        line = crop_metric_status_line(crop, profile, "air_temp")
        lines.append(line)
        if "-> alta" in line or "-> baja" in line:
            alerts.append(crop_display_label(crop))
    if alerts:
        lines.append("\nRecomendación: revisa primero " + ", ".join(alerts) + " porque presentan condición climática fuera de rango.")
    else:
        lines.append("\nRecomendación: condiciones climáticas generales favorables; mantén monitoreo normal.")
    return "\n".join(lines)


def _compose_parcel_metric(intent: IntentResult, context: Dict[str, Any], target_crop: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]]) -> str:
    if intent.intent == "temperature_status":
        return _compose_temperature_multicrop(context)
    if intent.intent == "wind_status":
        return _compose_wind(context)
    if intent.intent == "precipitation_status":
        return _compose_precipitation(context)
    if intent.intent == "air_humidity_status":
        return _compose_air_humidity(context)
    if intent.intent == "light_status":
        return _compose_light(context)
    if intent.intent == "soil_condition":
        return _compose_soil_condition(context, target_crop=target_crop, profile=profile)
    if intent.intent == "climate_status":
        return _compose_climate(context)
    return "No tengo una respuesta de parcela preparada para esa variable."


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

    health_lines = explain_health(health, target_crop, profile)
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


def _compose_no_crop_for_pest_or_fert(intent: IntentResult, context: Dict[str, Any]) -> str:
    active_crops = context.get("active_crops") or []
    crop_lines = [f"- {crop_status_line(c)}".strip() for c in active_crops]
    if intent.intent == "pest_or_disease":
        intro = "Para revisar plagas o enfermedades necesito el cultivo específico, porque no se manejan igual en cada cultivo."
        checks = (
            "Por ahora revisa señales generales: hojas mordidas o manchadas, insectos en el envés, "
            "tallos débiles, frutos dañados y humedad alta que favorezca hongos."
        )
    elif intent.intent == "fertilization":
        intro = "Para fertilización necesito el cultivo específico y, si existe, nutrientes reales cargados."
        checks = "Sin análisis de N, P, K o materia orgánica solo puedo dar orientación preventiva, no dosis exactas."
    else:
        intro = "Tienes varios cultivos activos y no detecté uno específico en tu pregunta."
        checks = ""
    return (
        intro + "\n\n" +
        "Cultivos activos:\n" + "\n".join(crop_lines) +
        ("\n\n" + checks if checks else "") +
        "\n\nPregunta por uno en particular, por ejemplo: 'plagas en mi tomate' o 'fertilización en maíz'."
    )


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
            "o una consulta como '¿cómo estoy de agua?', 'temperatura', 'viento' o 'plagas en el maíz'."
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
        lib_text = _clean_library_answer(context.get("raw_message", "") or "", rag) or _clean_library_answer("", rag)
        if lib_text:
            return lib_text
        return "No tengo información suficiente en la biblioteca para procesar esa solicitud."

    if not active_crops:
        return "Aún no tienes cultivos registrados. Agrega uno en Configuración para recibir diagnóstico de parcela."

    if intent.intent == "water_balance" and not target_crop:
        return _compose_water_multicrop(context)

    if intent.intent in _PARCEL_METRIC_INTENTS and not target_crop:
        return _compose_parcel_metric(intent, context, target_crop, profile)

    if target_crop:
        # Si se preguntó una variable parcelaria con un único cultivo, responder puntual sobre ese cultivo.
        if intent.intent in _PARCEL_METRIC_INTENTS and intent.intent != "soil_condition":
            return _compose_crop_answer(
                intent=intent,
                target_crop=target_crop,
                profile=profile,
                health=health,
                recommendation=None,
                rag_text=None,
                rag=None,
                mode=mode,
            )
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

    if intent.intent in {"pest_or_disease", "fertilization"}:
        return _compose_no_crop_for_pest_or_fert(intent, context)

    crop_lines = [f"- {crop_status_line(c)}".strip() for c in active_crops]
    return (
        "Tienes varios cultivos activos y no detecté uno específico en tu pregunta.\n\n"
        + "Cultivos activos:\n"
        + "\n".join(crop_lines)
        + "\n\nPregunta por uno en particular, por ejemplo: '¿cómo va mi maíz?' o 'plagas en mi frijol'."
    )
