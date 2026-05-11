from __future__ import annotations

from typing import Any, Dict, List, Optional

from milpa_ai_backend.core.logic.db import get_conn
from milpa_ai_backend.api.crops import (
    _aggregate_parcel_latest,
    _get_latest_global_edaphology,
    _evaluate_crop_health,
    _known_crop_names,
)

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

_PROFILE_BASE_COLUMNS = [
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
            crop["growth_stage"] = "maduracion"
        elif progress >= 45:
            crop["growth_stage"] = "desarrollo"
        elif progress >= 20:
            crop["growth_stage"] = "establecimiento"
        else:
            crop["growth_stage"] = "siembra"

    return crop


def _load_active_crops(conn, user_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        ""
        "SELECT c.id, c.user_id, c.crop_name, c.display_name, c.variety, c.planted_at, "
        "       c.expected_harvest_at, c.growth_stage, c.status, c.progress, "
        "       (SELECT sr.soil_moisture FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS soil_moisture, "
        "       (SELECT sr.air_temp FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS air_temp, "
        "       (SELECT sr.air_humidity FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS air_humidity, "
        "       (SELECT sr.light FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS light, "
        "       (SELECT sr.precipitation FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS precipitation, "
        "       (SELECT sr.wind_speed FROM sensor_readings sr WHERE sr.user_crop_id = c.id ORDER BY sr.created_at DESC LIMIT 1) AS wind_speed, "
        "       c.created_at "
        "FROM user_crops c "
        "WHERE c.user_id = ? AND COALESCE(c.status, 'activo') != 'inactivo' "
        "ORDER BY c.created_at DESC",
        (user_id,),
    ).fetchall()

    crops = [_format_crop_row(r) for r in rows]
    return [c for c in crops if c]


def _crop_variants(crop: Dict[str, Any]) -> List[str]:
    return [
        v
        for v in [crop.get("crop_name"), crop.get("display_name"), crop.get("variety")]
        if v
    ]


def _detect_active_crop(message: str, active_crops: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    text = normalize_text(message)
    if not text:
        return None

    best = None
    best_len = 0

    for crop in active_crops:
        for variant in _crop_variants(crop):
            v = normalize_text(variant)
            if not v or len(v) < 2:
                continue
            if v in text and len(v) > best_len:
                best = crop
                best_len = len(v)

    return best


def _detect_catalog_crop(message: str) -> Optional[str]:
    text = normalize_text(message)
    if not text:
        return None

    best = None
    best_len = 0

    for name in _known_crop_names():
        n = normalize_text(name)
        if not n or len(n) < 2:
            continue
        if n in text and len(n) > best_len:
            best = name
            best_len = len(n)

    return best


def _existing_columns(conn, table_name: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(r[1]) for r in rows]


def _load_profiles(conn, crop_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Carga perfiles agronómicos usando normalización en Python.

    No usamos `WHERE LOWER(crop_name) IN (...)` porque en SQLite LOWER() no resuelve
    bien todos los casos con acentos. Ejemplo: `maíz` vs `maiz`.
    """
    wanted = sorted({normalize_text(n) for n in crop_names if n})
    if not wanted:
        return {}

    try:
        available = set(_existing_columns(conn, "crop_profiles"))
        cols = [c for c in _PROFILE_BASE_COLUMNS if c in available]
        if "crop_name" not in cols:
            return {}

        rows = conn.execute(f"SELECT {', '.join(cols)} FROM crop_profiles").fetchall()
    except Exception:
        return {}

    profiles: Dict[str, Dict[str, Any]] = {}
    wanted_set = set(wanted)

    for row in rows:
        item = dict(zip(cols, row))
        key = normalize_text(item.get("crop_name"))
        if key in wanted_set:
            profiles[key] = item

    return profiles


def _health_index(health_by_crop: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in health_by_crop:
        crop_id = item.get("crop_id")
        if crop_id is not None:
            out[str(crop_id)] = item
    return out


def build_context(user_id: int, message: str) -> Dict[str, Any]:
    """
    Construye el contexto de AgroBot.

    Regla clave:
    - `target_crop` SOLO se asigna cuando el usuario menciona explícitamente
      un cultivo activo.
    - El fallback al primer cultivo activo NO se decide aquí. Lo decide service.py
      según intención, cantidad de cultivos y modo de consulta.
    """
    with get_conn() as conn:
        active_crops = _load_active_crops(conn, user_id)
        parcel_latest = _aggregate_parcel_latest(conn, user_id)
        global_edaphology = _get_latest_global_edaphology(conn)
        profiles_by_name = _load_profiles(conn, [c.get("crop_name") for c in active_crops])

        requested_active = _detect_active_crop(message, active_crops)
        requested_catalog = _detect_catalog_crop(message)

        fallback_crop = active_crops[0] if len(active_crops) == 1 else None
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
                        "crop_name": crop.get("crop_name"),
                        "label": "sin evaluar",
                        "score": None,
                        "summary": f"No se pudo evaluar la salud del cultivo: {exc}",
                        "factors": ["error_evaluacion_salud"],
                    }
                )

        return {
            "active_crops": active_crops,
            "target_crop": target_crop,
            "target_crop_source": "explicit" if target_crop else "none",
            "requested_active_crop": requested_active,
            "fallback_crop": fallback_crop,
            "requested_crop_name": requested_catalog,
            "rag_conflict": rag_conflict,
            "parcel_latest": parcel_latest,
            "global_edaphology": global_edaphology,
            "profiles_by_name": profiles_by_name,
            "health_by_crop": health_by_crop,
            "health_index": _health_index(health_by_crop),
        }
