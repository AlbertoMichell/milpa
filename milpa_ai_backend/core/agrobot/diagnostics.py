from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def crop_display_label(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return "cultivo"
    return crop.get("display_name") or crop.get("crop_name") or "cultivo"


def crop_status_line(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return ""

    parts: List[str] = []
    if crop.get("variety"):
        parts.append(f"variedad {crop['variety']}")
    if crop.get("growth_stage"):
        parts.append(f"etapa {crop['growth_stage']}")
    if crop.get("progress") is not None:
        parts.append(f"avance {int(crop['progress'])}%")

    label = crop_display_label(crop)
    if parts:
        return f"{label}: {', '.join(parts)}."
    return f"{label}."


def sensor_summary(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return ""

    parts: List[str] = []

    soil = _num(crop.get("soil_moisture"))
    temp = _num(crop.get("air_temp"))
    hum = _num(crop.get("air_humidity"))
    light = _num(crop.get("light"))
    precip = _num(crop.get("precipitation"))
    wind = _num(crop.get("wind_speed"))

    if soil is not None:
        parts.append(f"humedad del suelo {soil:.0f}%")
    if temp is not None:
        parts.append(f"temperatura {temp:.0f} °C")
    if hum is not None:
        parts.append(f"humedad relativa {hum:.0f}%")
    if light is not None:
        parts.append(f"luz {light:.0f}%")
    if precip is not None:
        parts.append(f"precipitación {precip:.1f} mm")
    if wind is not None:
        parts.append(f"viento {wind:.1f} km/h")

    return ", ".join(parts)


def profile_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return (
        _num(profile.get("optimal_soil_moisture_min")),
        _num(profile.get("optimal_soil_moisture_max")),
    )


def temp_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return (
        _num(profile.get("optimal_temp_min")),
        _num(profile.get("optimal_temp_max")),
    )


def air_humidity_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return (
        _num(profile.get("optimal_air_humidity_min")),
        _num(profile.get("optimal_air_humidity_max")),
    )


def water_status(soil_moisture: Optional[float], profile: Optional[Dict[str, Any]]) -> str:
    soil = _num(soil_moisture)
    if soil is None:
        return "sin datos"

    sm_min, sm_max = profile_range(profile)
    sm_min = sm_min if sm_min is not None else 35.0
    sm_max = sm_max if sm_max is not None else 75.0

    if soil < sm_min:
        return "baja"
    if soil > sm_max:
        return "alta"
    return "adecuada"


def range_text(lo: Optional[float], hi: Optional[float], suffix: str = "") -> str:
    if lo is None and hi is None:
        return "sin perfil"
    left = f"{lo:g}" if lo is not None else "?"
    right = f"{hi:g}" if hi is not None else "?"
    return f"{left}-{right}{suffix}"


def profile_comparison(crop: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]]) -> List[str]:
    if not crop:
        return []

    lines: List[str] = []

    soil = _num(crop.get("soil_moisture"))
    sm_min, sm_max = profile_range(profile)
    if soil is not None:
        status = water_status(soil, profile)
        lines.append(
            f"Humedad del suelo: {soil:.0f}% frente al rango recomendado "
            f"{range_text(sm_min, sm_max, '%')} -> {status}."
        )

    temp = _num(crop.get("air_temp"))
    t_min, t_max = temp_range(profile)
    if temp is not None:
        if t_min is None and t_max is None:
            t_status = "sin perfil"
        elif t_min is not None and temp < t_min:
            t_status = "baja"
        elif t_max is not None and temp > t_max:
            t_status = "alta"
        else:
            t_status = "adecuada"
        lines.append(
            f"Temperatura: {temp:.0f} °C frente al rango recomendado "
            f"{range_text(t_min, t_max, ' °C')} -> {t_status}."
        )

    air_h = _num(crop.get("air_humidity"))
    ah_min, ah_max = air_humidity_range(profile)
    if air_h is not None:
        if ah_min is None and ah_max is None:
            h_status = "sin perfil"
        elif ah_min is not None and air_h < ah_min:
            h_status = "baja"
        elif ah_max is not None and air_h > ah_max:
            h_status = "alta"
        else:
            h_status = "adecuada"
        lines.append(
            f"Humedad ambiental: {air_h:.0f}% frente al rango recomendado "
            f"{range_text(ah_min, ah_max, '%')} -> {h_status}."
        )

    if not lines and not profile:
        lines.append("No hay perfil agronómico suficiente para comparar rangos ideales.")
    elif not lines:
        lines.append("No hay lecturas suficientes para comparar contra el perfil ideal.")

    return lines


def explain_health(health: Optional[Dict[str, Any]]) -> List[str]:
    if not health:
        return ["No hay evaluación de salud disponible para este cultivo."]

    lines: List[str] = []
    label = health.get("label") or "sin evaluar"
    score = health.get("score")
    summary = health.get("summary")
    factors = health.get("factors") or []

    if score is not None:
        lines.append(f"Salud/calidad calculada: {label} (score {score}).")
    else:
        lines.append(f"Salud/calidad calculada: {label}.")

    if summary:
        lines.append(str(summary).strip())

    if isinstance(factors, list) and factors:
        clean_factors = [str(f).strip() for f in factors if str(f).strip()]
        if clean_factors:
            lines.append("Factores detectados: " + "; ".join(clean_factors) + ".")

    return lines


def classify_context_severity(health: Optional[Dict[str, Any]]) -> str:
    if not health:
        return "sin_datos"

    label = str(health.get("label") or "").strip().lower()
    score = _num(health.get("score"))

    if "crit" in label or (score is not None and score < 45):
        return "critico"
    if "vigil" in label or (score is not None and score < 70):
        return "vigilancia"
    if "salud" in label or "estable" in label or (score is not None and score >= 70):
        return "normal"
    return "sin_datos"


def build_action_hint(
    intent_name: str,
    crop: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
    health: Optional[Dict[str, Any]],
    recommendation: Optional[Dict[str, Any]],
) -> str:
    if recommendation and recommendation.get("action"):
        return f"Atiende la recomendación registrada: {recommendation['action']}."

    if not crop:
        return "Selecciona un cultivo específico para recibir una acción puntual."

    soil = _num(crop.get("soil_moisture"))
    status = water_status(soil, profile)
    severity = classify_context_severity(health)

    if status == "baja":
        return "Programa riego de recuperación y vuelve a revisar la humedad en 4 a 6 horas."
    if status == "alta":
        return "Suspende riego temporalmente, revisa drenaje y verifica si hay encharcamiento."
    if severity == "critico":
        return "Prioriza revisión en campo y valida sensores antes de aplicar manejo correctivo."
    if intent_name == "pest_or_disease":
        return "Revisa hojas, tallos y envés para confirmar síntomas antes de aplicar control."
    if intent_name == "fertilization":
        return "Valida etapa del cultivo y condición del suelo antes de fertilizar."
    if intent_name == "soil_condition":
        return "Contrasta pH, conductividad y humedad con el perfil del cultivo antes de corregir suelo."

    return "Mantén monitoreo y registra una nueva lectura en el próximo recorrido."
