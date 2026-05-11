from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def crop_display_label(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return "cultivo"
    return crop.get("display_name") or crop.get("crop_name") or "cultivo"


def crop_status_line(crop: Optional[Dict[str, Any]]) -> str:
    if not crop:
        return ""
    parts = []
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
    parts = []
    if crop.get("soil_moisture") is not None:
        parts.append(f"humedad suelo {float(crop['soil_moisture']):.0f}%")
    if crop.get("air_temp") is not None:
        parts.append(f"{float(crop['air_temp']):.0f}C")
    if crop.get("air_humidity") is not None:
        parts.append(f"HR {float(crop['air_humidity']):.0f}%")
    if crop.get("light") is not None:
        parts.append(f"luz {float(crop['light']):.0f}%")
    return ", ".join(parts)


def profile_range(profile: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not profile:
        return None, None
    return profile.get("optimal_soil_moisture_min"), profile.get("optimal_soil_moisture_max")


def water_status(soil_moisture: Optional[float], profile: Optional[Dict[str, Any]]) -> str:
    if soil_moisture is None:
        return "sin datos"
    sm_min, sm_max = profile_range(profile)
    sm_min = sm_min if sm_min is not None else 35
    sm_max = sm_max if sm_max is not None else 75
    if soil_moisture < sm_min:
        return "baja"
    if soil_moisture > sm_max:
        return "alta"
    return "adecuada"
