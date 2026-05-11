from __future__ import annotations

from typing import Any, Dict, List, Optional

from milpa_ai_backend.api.crops import (
    _aggregate_parcel_latest,
    _evaluate_crop_health,
    _get_latest_global_edaphology,
    _known_crop_names,
)
from milpa_ai_backend.core.logic.db import get_conn

from .intent import normalize_text


_CROP_COLS = [
    "id",
    "user_id",
    "crop_name",
    "display_name",
    "variety",
    "planted_at",
    "expected_harvest_at",
    "growth_stage",
    "status",
    "progress",
    "soil_moisture",
    "air_temp",
    "air_humidity",
    "light",
    "precipitation",
    "wind_speed",
    "created_at",
]

_PROFILE_COLS = [
    "crop_name",
    "optimal_temp_min",
    "optimal_temp_max",
    "optimal_soil_moisture_min",
    "optimal_soil_moisture_max",
    "optimal_air_humidity_min",
    "optimal_air_humidity_max",
    "optimal_ph_min",
    "optimal_ph_max",
    "notes",
]


def _format_crop_row(row: Optional[tuple]) -> Optional[Dict[str, Any]]:
    if not row:
        return None

    crop = dict(zip(_CROP_COLS, row))

    if not crop.get("display_name"):
        base = (crop.get("crop_name") or "Cultivo").strip()
        variety = (crop.get("variety") or "").strip()
        crop["display_name"] = " ".join(part for part in [base.capitalize(), variety] if part)

    if not crop.get("growth_stage"):
        progress = int(crop.get("progress") or 0)
        if progress >= 75:
            crop["growth_stage"] = "maduración"
        elif progress >= 45:
            crop["growth_stage"] = "desarrollo"
        elif progress >= 20:
            crop["growth_stage"] = "establecimiento"
        else:
            crop["growth_stage"] = "siembra"

    return crop


def _load_active_crops(conn, user_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.user_id,
            c.crop_name,
            c.display_name,
            c.variety,
            c.planted_at,
            c.expected_harvest_at,
            c.growth_stage,
            c.status,
            c.progress,
            (
                SELECT sr.soil_moisture
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS soil_moisture,
            (
                SELECT sr.air_temp
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS air_temp,
            (
                SELECT sr.air_humidity
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS air_humidity,
            (
                SELECT sr.light
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS light,
            (
                SELECT sr.precipitation
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS precipitation,
            (
                SELECT sr.wind_speed
                FROM sensor_readings sr
                WHERE sr.user_crop_id = c.id
                ORDER BY sr.created_at DESC
                LIMIT 1
            ) AS wind_speed,
            c.created_at
        FROM user_crops c
        WHERE c.user_id = ?
          AND COALESCE(c.status, 'activo') != 'inactivo'
        ORDER BY c.created_at DESC
        """,
        (int(user_id),),
    ).fetchall()

    crops = [_format_crop_row(row) for row in rows]
    return [crop for crop in crops if crop]


def _crop_variants(crop: Dict[str, Any]) -> List[str]:
    return [
        str(value)
        for value in [crop.get("crop_name"), crop.get("display_name"), crop.get("variety")]
        if value
    ]


def _detect_active_crop(message: str, active_crops: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    text = normalize_text(message)
    if not text:
        return None

    best: Optional[Dict[str, Any]] = None
    best_len = 0

    for crop in active_crops:
        for variant in _crop_variants(crop):
            normalized_variant = normalize_text(variant)
            if not normalized_variant or len(normalized_variant) < 2:
                continue
            if normalized_variant in text and len(normalized_variant) > best_len:
                best = crop
                best_len = len(normalized_variant)

    return best


def _detect_catalog_crop(message: str) -> Optional[str]:
    text = normalize_text(message)
    if not text:
        return None

    best: Optional[str] = None
    best_len = 0

    for name in _known_crop_names():
        normalized_name = normalize_text(str(name))
        if not normalized_name or len(normalized_name) < 2:
            continue
        if normalized_name in text and len(normalized_name) > best_len:
            best = str(name)
            best_len = len(normalized_name)

    return best


def _load_profiles(conn, crop_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Carga perfiles de crop_profiles usando comparación normalizada en Python.

    Esto evita fallos por acentos o mayúsculas/minúsculas. Por ejemplo:
    `maíz`, `maiz`, `Maiz` y `MAÍZ` deben resolver al mismo perfil.
    """
    wanted = {normalize_text(name) for name in crop_names if name}
    if not wanted:
        return {}

    try:
        rows = conn.execute(
            """
            SELECT
                crop_name,
                optimal_temp_min,
                optimal_temp_max,
                optimal_soil_moisture_min,
                optimal_soil_moisture_max,
                optimal_air_humidity_min,
                optimal_air_humidity_max,
                optimal_ph_min,
                optimal_ph_max,
                notes
            FROM crop_profiles
            """
        ).fetchall()
    except Exception:
        return {}

    profiles: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        item = dict(zip(_PROFILE_COLS, row))
        key = normalize_text(item.get("crop_name"))
        if key in wanted:
            profiles[key] = item

    return profiles


def build_context(user_id: int, message: str) -> Dict[str, Any]:
    """
    Construye el contexto real de AgroBot.

    Regla importante:
    - `target_crop` solo se asigna si el usuario menciona explícitamente un cultivo activo.
    - `fallback_crop` se informa aparte para que service.py decida si debe usarse.
    - Nunca se debe tomar automáticamente el primer cultivo cuando hay varios cultivos activos.
    """
    with get_conn() as conn:
        active_crops = _load_active_crops(conn, int(user_id))
        parcel_latest = _aggregate_parcel_latest(conn, int(user_id))
        global_edaphology = _get_latest_global_edaphology(conn)
        profiles_by_name = _load_profiles(conn, [crop.get("crop_name") for crop in active_crops])

        requested_active = _detect_active_crop(message, active_crops)
        requested_catalog = _detect_catalog_crop(message)
        fallback_crop = active_crops[0] if active_crops else None

        target_crop = requested_active
        rag_conflict = bool(requested_catalog and not requested_active)

        health_by_crop: List[Dict[str, Any]] = []
        for crop in active_crops:
            profile = profiles_by_name.get(normalize_text(crop.get("crop_name")))
            try:
                health_by_crop.append(_evaluate_crop_health(crop, parcel_latest, profile))
            except Exception as exc:
                health_by_crop.append(
                    {
                        "crop_id": crop.get("id"),
                        "label": "sin evaluar",
                        "score": None,
                        "summary": f"No se pudo evaluar salud del cultivo: {exc}",
                        "factors": [],
                    }
                )

    return {
        "active_crops": active_crops,
        "target_crop": target_crop,
        "requested_active_crop": requested_active,
        "fallback_crop": fallback_crop,
        "requested_crop_name": requested_catalog,
        "rag_conflict": rag_conflict,
        "parcel_latest": parcel_latest,
        "global_edaphology": global_edaphology,
        "profiles_by_name": profiles_by_name,
        "health_by_crop": health_by_crop,
        "target_crop_source": "explicit" if target_crop else "none",
    }
