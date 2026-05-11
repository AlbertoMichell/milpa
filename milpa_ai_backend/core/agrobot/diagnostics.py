from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def crop_display_label(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return "cultivo"
    return str(crop.get("display_name") or crop.get("crop_name") or "cultivo")


def crop_status_line(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return ""
    parts: List[str] = []
    if crop.get("variety"):
        parts.append(f"variedad {crop['variety']}")
    if crop.get("growth_stage"):
        parts.append(f"etapa {crop['growth_stage']}")
    if crop.get("progress") is not None:
        try:
            parts.append(f"avance {int(float(crop['progress']))}%")
        except (TypeError, ValueError):
            parts.append(f"avance {crop['progress']}%")
    label = crop_display_label(crop)
    return f"{label}: {', '.join(parts)}." if parts else f"{label}."


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


def range_text(lo: Optional[float], hi: Optional[float], suffix: str = "") -> str:
    if lo is None and hi is None:
        return "sin perfil"
    left = f"{lo:g}" if lo is not None else "?"
    right = f"{hi:g}" if hi is not None else "?"
    return f"{left}-{right}{suffix}"


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
    return (_num(profile.get("optimal_temp_min")), _num(profile.get("optimal_temp_max")))


def air_humidity_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return (
        _num(profile.get("optimal_air_humidity_min")),
        _num(profile.get("optimal_air_humidity_max")),
    )


def ph_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return (_num(profile.get("optimal_ph_min")), _num(profile.get("optimal_ph_max")))


def _bounded_status(value: Any, lo: Optional[float], hi: Optional[float], default_lo: Optional[float] = None, default_hi: Optional[float] = None) -> str:
    val = _num(value)
    if val is None:
        return "sin datos"
    lo = lo if lo is not None else default_lo
    hi = hi if hi is not None else default_hi
    if lo is None and hi is None:
        return "sin perfil"
    if lo is not None and val < lo:
        return "baja"
    if hi is not None and val > hi:
        return "alta"
    return "adecuada"


def water_status(soil_moisture: Optional[float], profile: Optional[Dict[str, Any]]) -> str:
    sm_min, sm_max = profile_range(profile)
    return _bounded_status(soil_moisture, sm_min, sm_max, 35.0, 75.0)


def temperature_status(temp: Any, profile: Optional[Dict[str, Any]]) -> str:
    t_min, t_max = temp_range(profile)
    return _bounded_status(temp, t_min, t_max, 12.0, 34.0)


def air_humidity_status(value: Any, profile: Optional[Dict[str, Any]]) -> str:
    ah_min, ah_max = air_humidity_range(profile)
    return _bounded_status(value, ah_min, ah_max, 40.0, 80.0)


def ph_status(value: Any, profile: Optional[Dict[str, Any]]) -> str:
    p_min, p_max = ph_range(profile)
    return _bounded_status(value, p_min, p_max, 5.5, 7.5)


def wind_status(value: Any) -> str:
    wind = _num(value)
    if wind is None:
        return "sin datos"
    if wind < 15:
        return "normal"
    if wind < 30:
        return "moderado"
    return "alto"


def precipitation_status(value: Any) -> str:
    rain = _num(value)
    if rain is None:
        return "sin datos"
    if rain <= 0:
        return "sin lluvia reciente"
    if rain < 5:
        return "lluvia ligera"
    if rain < 20:
        return "lluvia moderada"
    return "lluvia alta"


def light_status(value: Any) -> str:
    light = _num(value)
    if light is None:
        return "sin datos"
    if light < 35:
        return "baja"
    if light > 90:
        return "alta"
    return "adecuada"


def _status_word(metric: str, crop: Dict[str, Any], profile: Optional[Dict[str, Any]], global_edaphology: Optional[Dict[str, Any]] = None) -> str:
    global_edaphology = global_edaphology or {}
    if metric == "soil_moisture":
        return water_status(crop.get("soil_moisture"), profile)
    if metric == "air_temp":
        return temperature_status(crop.get("air_temp"), profile)
    if metric == "air_humidity":
        return air_humidity_status(crop.get("air_humidity"), profile)
    if metric == "light":
        return light_status(crop.get("light"))
    if metric == "wind_speed":
        return wind_status(crop.get("wind_speed"))
    if metric == "precipitation":
        return precipitation_status(crop.get("precipitation"))
    if metric == "ph":
        return ph_status(global_edaphology.get("ph"), profile)
    if metric == "conductivity":
        c = _num(global_edaphology.get("conductivity"))
        if c is None:
            return "sin datos"
        if c <= 1.5:
            return "normal"
        if c <= 3.0:
            return "moderada"
        return "alta"
    return "sin datos"


def profile_comparison(crop: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]]) -> List[str]:
    if not crop:
        return []
    lines: List[str] = []

    soil = _num(crop.get("soil_moisture"))
    sm_min, sm_max = profile_range(profile)
    if soil is not None:
        lines.append(
            f"Humedad del suelo: {soil:.0f}% frente al rango recomendado "
            f"{range_text(sm_min, sm_max, '%')} -> {water_status(soil, profile)}."
        )

    temp = _num(crop.get("air_temp"))
    t_min, t_max = temp_range(profile)
    if temp is not None:
        lines.append(
            f"Temperatura: {temp:.0f} °C frente al rango recomendado "
            f"{range_text(t_min, t_max, ' °C')} -> {temperature_status(temp, profile)}."
        )

    air_h = _num(crop.get("air_humidity"))
    ah_min, ah_max = air_humidity_range(profile)
    if air_h is not None:
        lines.append(
            f"Humedad ambiental: {air_h:.0f}% frente al rango recomendado "
            f"{range_text(ah_min, ah_max, '%')} -> {air_humidity_status(air_h, profile)}."
        )

    if not lines and not profile:
        lines.append("No hay perfil agronómico suficiente para comparar rangos ideales.")
    elif not lines:
        lines.append("No hay lecturas suficientes para comparar contra el perfil ideal.")
    return lines


def range_observations(crop: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]]) -> List[str]:
    if not crop:
        return []
    obs: List[str] = []
    soil_status = water_status(crop.get("soil_moisture"), profile)
    temp_status = temperature_status(crop.get("air_temp"), profile)
    hum_status = air_humidity_status(crop.get("air_humidity"), profile)
    if soil_status == "baja":
        obs.append("humedad del suelo por debajo del rango recomendado")
    elif soil_status == "alta":
        obs.append("humedad del suelo por encima del rango recomendado")
    if temp_status == "baja":
        obs.append("temperatura por debajo del rango recomendado")
    elif temp_status == "alta":
        obs.append("temperatura por encima del rango recomendado")
    if hum_status == "baja":
        obs.append("humedad ambiental por debajo del rango recomendado")
    elif hum_status == "alta":
        obs.append("humedad ambiental por encima del rango recomendado")
    return obs


def _factor_to_text(factor: Any) -> Optional[str]:
    if factor is None:
        return None
    if isinstance(factor, dict):
        message = factor.get("message") or factor.get("summary") or factor.get("label")
        code = factor.get("code")
        severity = factor.get("severity")
        if message:
            return f"{message} ({severity})" if severity else str(message)
        if code:
            return str(code)
        return None
    text = str(factor).strip()
    if not text or text == "{}":
        return None
    return text


def explain_health(
    health: Optional[Dict[str, Any]],
    crop: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if not health:
        return ["No hay evaluación de salud disponible para este cultivo."]
    lines: List[str] = []
    label = health.get("label") or "sin evaluar"
    score = health.get("score")
    summary = health.get("summary") or ""
    factors = health.get("factors") or []
    obs = range_observations(crop, profile)

    suffix = ", con observaciones de rango" if obs else ""
    if score is not None:
        lines.append(f"Salud/calidad calculada: {label} (score {score}){suffix}.")
    else:
        lines.append(f"Salud/calidad calculada: {label}{suffix}.")
    if summary:
        lines.append(str(summary).strip())
    if obs:
        lines.append("Observaciones de sensores: " + "; ".join(obs) + ".")
    if isinstance(factors, list) and factors:
        clean_factors = [_factor_to_text(factor) for factor in factors]
        clean_factors = [factor for factor in clean_factors if factor]
        if clean_factors:
            lines.append("Factores detectados: " + "; ".join(clean_factors) + ".")
    return lines


def classify_context_severity(health: Optional[Dict[str, Any]], crop: Optional[Dict[str, Any]] = None, profile: Optional[Dict[str, Any]] = None) -> str:
    obs = range_observations(crop, profile)
    if not health:
        return "vigilancia" if obs else "sin_datos"
    label = str(health.get("label") or "").strip().lower()
    score = _num(health.get("score"))
    if "crit" in label or (score is not None and score < 45):
        return "critico"
    if "vigil" in label or (score is not None and score < 70) or obs:
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
    severity = classify_context_severity(health, crop, profile)
    temp_st = temperature_status(crop.get("air_temp"), profile)
    wind_st = wind_status(crop.get("wind_speed"))
    rain_st = precipitation_status(crop.get("precipitation"))

    if status == "baja":
        return "Programa riego de recuperación y vuelve a revisar la humedad en 4 a 6 horas."
    if status == "alta":
        return "Suspende el riego temporalmente, revisa drenaje y verifica si hay encharcamiento."
    if temp_st == "alta":
        return "Refuerza monitoreo térmico; evita labores estresantes en horas de mayor calor."
    if wind_st == "alto":
        return "Evita aplicaciones foliares y revisa tutores o estructuras sensibles al viento."
    if rain_st == "lluvia alta":
        return "Revisa drenaje y síntomas de enfermedades asociadas a exceso de humedad."
    if severity == "critico":
        return "Prioriza una revisión en campo y valida sensores antes de aplicar manejo correctivo."
    if intent_name == "pest_or_disease":
        return "Revisa hojas, tallos, envés y frutos para confirmar síntomas antes de aplicar control."
    if intent_name == "fertilization":
        return "Valida etapa del cultivo, nutrientes disponibles y humedad antes de fertilizar."
    if intent_name == "soil_condition":
        return "Contrasta pH, conductividad y humedad con el perfil del cultivo antes de corregir suelo."
    if intent_name in {"temperature_status", "wind_status", "precipitation_status", "climate_status"}:
        return "Mantén monitoreo climático y actualiza lecturas si cambian las condiciones."
    return "Mantén monitoreo y registra una nueva lectura en el próximo recorrido."


def metric_value_from_crop(crop: Dict[str, Any], metric: str) -> Optional[float]:
    return _num(crop.get(metric))


def metric_value_from_context(context: Dict[str, Any], metric: str) -> Optional[float]:
    parcel = context.get("parcel_latest") or {}
    global_reading = context.get("global_edaphology") or {}
    for source in (parcel, global_reading):
        if source.get(metric) is not None:
            return _num(source.get(metric))
    if metric == "ph":
        return _num(global_reading.get("ph"))
    if metric == "conductivity":
        return _num(global_reading.get("conductivity"))
    return None


def crop_metric_status_line(crop: Dict[str, Any], profile: Optional[Dict[str, Any]], metric: str, global_edaphology: Optional[Dict[str, Any]] = None) -> str:
    label = crop_display_label(crop)
    status = _status_word(metric, crop, profile, global_edaphology)
    value = metric_value_from_crop(crop, metric)
    if metric == "air_temp":
        value_txt = f"{value:.0f} °C" if value is not None else "sin dato"
        lo, hi = temp_range(profile)
        return f"- {label}: {value_txt} / rango {range_text(lo, hi, ' °C')} -> {status}."
    if metric == "soil_moisture":
        value_txt = f"{value:.0f}%" if value is not None else "sin dato"
        lo, hi = profile_range(profile)
        return f"- {label}: {value_txt} / rango {range_text(lo, hi, '%')} -> {status}."
    if metric == "air_humidity":
        value_txt = f"{value:.0f}%" if value is not None else "sin dato"
        lo, hi = air_humidity_range(profile)
        return f"- {label}: {value_txt} / rango {range_text(lo, hi, '%')} -> {status}."
    if metric == "light":
        value_txt = f"{value:.0f}%" if value is not None else "sin dato"
        return f"- {label}: luz {value_txt} -> {status}."
    if metric == "wind_speed":
        value_txt = f"{value:.1f} km/h" if value is not None else "sin dato"
        return f"- {label}: viento {value_txt} -> {status}."
    if metric == "precipitation":
        value_txt = f"{value:.1f} mm" if value is not None else "sin dato"
        return f"- {label}: precipitación {value_txt} -> {status}."
    if metric == "ph":
        g = global_edaphology or {}
        value = _num(g.get("ph"))
        lo, hi = ph_range(profile)
        value_txt = f"{value:.2f}" if value is not None else "sin dato"
        return f"- {label}: pH global {value_txt} / rango {range_text(lo, hi, '')} -> {status}."
    if metric == "conductivity":
        g = global_edaphology or {}
        value = _num(g.get("conductivity"))
        value_txt = f"{value:.2f} dS/m" if value is not None else "sin dato"
        return f"- {label}: conductividad global {value_txt} -> {status}."
    return f"- {label}: sin comparación disponible."
