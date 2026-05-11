# milpa_ai_backend/api/crops.py
# ------------------------------------------------------------
# CRUD de cultivos del usuario, lecturas de sensores y
# endpoint de recomendación inteligente (sensor → RAG query).
# ------------------------------------------------------------
from __future__ import annotations

import logging
import json
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from milpa_ai_backend.core.logic.db import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()

_PARCEL_GUIDE_JSON = Path(__file__).resolve().parents[1] / "models" / "parcel_micrometeorology_reference.json"


def _load_parcel_monitoring_guidelines() -> Dict[str, Any]:
    """Referencias de parcela (independiente del cultivo) — paralelas a la guía en biblioteca RAG."""
    try:
        with open(_PARCEL_GUIDE_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# ───────── Modelos Pydantic ─────────

class CropCreate(BaseModel):
    user_id: int
    crop_name: str
    display_name: Optional[str] = None
    variety: Optional[str] = None
    planted_at: Optional[str] = None
    expected_harvest_at: Optional[str] = None
    growth_stage: Optional[str] = None
    image_path: Optional[str] = None
    status: Optional[str] = "activo"
    progress: Optional[int] = 0
    notes: Optional[str] = None

class CropUpdate(BaseModel):
    crop_name: Optional[str] = None
    display_name: Optional[str] = None
    variety: Optional[str] = None
    planted_at: Optional[str] = None
    expected_harvest_at: Optional[str] = None
    growth_stage: Optional[str] = None
    image_path: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    notes: Optional[str] = None

class CropOut(BaseModel):
    id: int
    user_id: int
    crop_name: str
    display_name: Optional[str] = None
    variety: Optional[str] = None
    planted_at: Optional[str] = None
    expected_harvest_at: Optional[str] = None
    growth_stage: Optional[str] = None
    image_path: Optional[str] = None
    status: str
    progress: int
    notes: Optional[str] = None
    created_at: str
    sensor_x_pct: Optional[float] = None
    sensor_y_pct: Optional[float] = None

class SensorCreate(BaseModel):
    user_crop_id: int
    soil_moisture: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    light: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None

class SensorOut(BaseModel):
    id: int
    user_crop_id: int
    soil_moisture: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    light: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    created_at: str


class GlobalEdaphologyCreate(BaseModel):
    location_name: Optional[str] = "general"
    soil_temp: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    soil_moisture: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    ph: Optional[float] = None
    conductivity: Optional[float] = None
    notes: Optional[str] = None


class GlobalEdaphologyOut(BaseModel):
    id: int
    location_name: str
    soil_temp: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    soil_moisture: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    ph: Optional[float] = None
    conductivity: Optional[float] = None
    notes: Optional[str] = None
    created_at: str


class GlobalEdaphologyUpdate(BaseModel):
    """PATCH del registro edafológico global más reciente; campos opcionales."""
    location_name: Optional[str] = None
    soil_temp: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    soil_moisture: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    ph: Optional[float] = None
    conductivity: Optional[float] = None
    notes: Optional[str] = None


class CropProfileOut(BaseModel):
    id: int
    crop_name: str
    variety: Optional[str] = None
    optimal_temp_min: Optional[float] = None
    optimal_temp_max: Optional[float] = None
    optimal_soil_moisture_min: Optional[float] = None
    optimal_soil_moisture_max: Optional[float] = None
    optimal_air_humidity_min: Optional[float] = None
    optimal_air_humidity_max: Optional[float] = None
    optimal_ph_min: Optional[float] = None
    optimal_ph_max: Optional[float] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    cycle_days: Optional[int] = None


class CropProfileUpdate(BaseModel):
    """PATCH parcial del perfil agronómico; todos los campos opcionales."""
    variety: Optional[str] = None
    optimal_temp_min: Optional[float] = None
    optimal_temp_max: Optional[float] = None
    optimal_soil_moisture_min: Optional[float] = None
    optimal_soil_moisture_max: Optional[float] = None
    optimal_air_humidity_min: Optional[float] = None
    optimal_air_humidity_max: Optional[float] = None
    optimal_ph_min: Optional[float] = None
    optimal_ph_max: Optional[float] = None
    notes: Optional[str] = None
    cycle_days: Optional[int] = None


class DatasetApplySensorIn(BaseModel):
    """
    Inserta filas en `sensor_readings` (lectura efectiva por cultivo).
    Si `user_crop_id` es null, replica la misma lectura en todos los cultivos activos del usuario.
    """
    user_id: int
    user_crop_id: Optional[int] = None
    soil_moisture: Optional[float] = None
    air_temp: Optional[float] = None
    air_humidity: Optional[float] = None
    light: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None

class RecommendationOut(BaseModel):
    id: int
    user_crop_id: int
    query_text: str
    action: str
    priority: str
    detail_html: Optional[str] = None
    citations: Optional[str] = None
    status: str
    faithfulness: Optional[float] = None
    created_at: str

class RecommendationRequest(BaseModel):
    user_crop_id: int
    force: bool = False

class RecommendationUpdateStatus(BaseModel):
    status: str  # pendiente | aplicada | pospuesta


# ───────── Helpers ─────────

def _row_to_dict(row, columns):
    if row is None:
        return None
    return dict(zip(columns, row))


def _get_latest_global_edaphology(conn) -> Optional[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes, created_at "
        "FROM edaphology_global_readings ORDER BY created_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    cols = [
        "id", "location_name", "soil_temp", "air_temp", "air_humidity", "soil_moisture",
        "precipitation", "wind_speed", "ph", "conductivity", "notes", "created_at"
    ]
    return _row_to_dict(row, cols)


def _normalize_crop_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _sanitize_recommendation_detail(detail_html: str, target_crop: str) -> str:
    """
    Elimina líneas de detalle que mencionan cultivos NO objetivo cuando el
    usuario está operando un cultivo específico.

    El conjunto de cultivos potencialmente "rivales" se lee dinámicamente desde
    `crop_profiles` (vía `_known_crop_names()`), no de una lista cerrada en
    código. Así, agregar/eliminar cultivos en la BD ajusta el saneamiento sin
    tocar el motor de recomendaciones ni introducir lógica especial por cultivo.
    """
    target = _normalize_crop_name(target_crop)
    if not detail_html or not target:
        return detail_html or ""

    catalog = _known_crop_names()
    if target not in catalog:
        catalog = catalog + [target]
    blocked = [c for c in catalog if c and _normalize_crop_name(c) and _normalize_crop_name(c) != target]
    if not blocked:
        return detail_html

    lines = detail_html.splitlines()
    filtered = []
    for line in lines:
        normalized = _normalize_crop_name(line)
        if any(_normalize_crop_name(alias) in normalized for alias in blocked):
            continue
        filtered.append(line)
    clean = "\n".join(filtered).strip() or detail_html
    for alias in blocked:
        clean = re.sub(rf"(?i)\b{re.escape(alias)}\b", "", clean)
    return clean


def _format_crop_payload(row) -> Optional[Dict[str, Any]]:
    cols = [
        "id", "user_id", "crop_name", "display_name", "variety", "planted_at",
        "expected_harvest_at", "growth_stage", "image_path", "status", "progress",
        "notes", "created_at", "sensor_x_pct", "sensor_y_pct"
    ]
    crop = _row_to_dict(row, cols)
    if not crop:
        return None
    if not crop.get("display_name"):
        base_name = (crop.get("crop_name") or "Cultivo").strip()
        crop["display_name"] = " ".join(
            part for part in [base_name.capitalize(), (crop.get("variety") or "").strip()] if part
        )
    if not crop.get("growth_stage"):
        progress = crop.get("progress") or 0
        if progress >= 75:
            crop["growth_stage"] = "maduración"
        elif progress >= 45:
            crop["growth_stage"] = "desarrollo"
        elif progress >= 20:
            crop["growth_stage"] = "establecimiento"
        else:
            crop["growth_stage"] = "siembra"
    return crop


# ───────── CULTIVOS CRUD ─────────

@router.get("/api/crops/{user_id}", response_model=List[CropOut])
async def list_crops(user_id: int):
    """Lista cultivos de un usuario."""
    with get_conn() as conn:
        conn.row_factory = None
        cur = conn.execute(
            "SELECT id, user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, growth_stage, image_path, status, progress, notes, created_at, sensor_x_pct, sensor_y_pct "
            "FROM user_crops WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        )
        rows = cur.fetchall()
    return [_format_crop_payload(r) for r in rows]


@router.post("/api/crops", response_model=CropOut, status_code=201)
async def create_crop(data: CropCreate):
    """Registra un nuevo cultivo."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO user_crops (user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, growth_stage, image_path, status, progress, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.user_id,
                data.crop_name.strip(),
                data.display_name,
                data.variety,
                data.planted_at,
                data.expected_harvest_at,
                data.growth_stage,
                data.image_path,
                data.status or "activo",
                max(0, min(100, int(data.progress or 0))),
                data.notes,
            )
        )
        conn.commit()
        row_id = cur.lastrowid
        cur2 = conn.execute(
            "SELECT id, user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, growth_stage, image_path, status, progress, notes, created_at, sensor_x_pct, sensor_y_pct "
            "FROM user_crops WHERE id = ?", (row_id,)
        )
        row = cur2.fetchone()
    return _format_crop_payload(row)


@router.patch("/api/crops/{crop_id}", response_model=CropOut)
async def update_crop(crop_id: int, data: CropUpdate):
    """Actualiza campos de un cultivo."""
    sets = []
    vals = []
    for field in [
        "crop_name", "display_name", "variety", "planted_at", "expected_harvest_at",
        "growth_stage", "image_path", "status", "progress", "notes"
    ]:
        v = getattr(data, field, None)
        if v is not None:
            if field == "progress":
                v = max(0, min(100, int(v)))
            sets.append(f"{field} = ?")
            vals.append(v)
    if not sets:
        raise HTTPException(400, "Nada que actualizar")
    vals.append(crop_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE user_crops SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
        cur = conn.execute(
            "SELECT id, user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, growth_stage, image_path, status, progress, notes, created_at, sensor_x_pct, sensor_y_pct "
            "FROM user_crops WHERE id = ?", (crop_id,)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Cultivo no encontrado")
    return _format_crop_payload(row)


@router.delete("/api/crops/{crop_id}", status_code=204)
async def delete_crop(crop_id: int):
    """Elimina un cultivo y sus datos asociados."""
    with get_conn() as conn:
        conn.execute("DELETE FROM sensor_readings WHERE user_crop_id = ?", (crop_id,))
        conn.execute("DELETE FROM recommendations WHERE user_crop_id = ?", (crop_id,))
        conn.execute("DELETE FROM user_crops WHERE id = ?", (crop_id,))
        conn.commit()


# ───────── SENSORES CRUD ─────────

@router.get("/api/sensors/{user_crop_id}", response_model=List[SensorOut])
async def list_sensor_readings(user_crop_id: int, limit: int = 50):
    """Últimas lecturas de sensores de un cultivo."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id, user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at "
            "FROM sensor_readings WHERE user_crop_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_crop_id, limit)
        )
        rows = cur.fetchall()
    cols = ["id", "user_crop_id", "soil_moisture", "air_temp", "air_humidity", "light", "precipitation", "wind_speed", "created_at"]
    return [_row_to_dict(r, cols) for r in rows]


@router.post("/api/sensors", response_model=SensorOut, status_code=201)
async def create_sensor_reading(data: SensorCreate):
    """Registra una nueva lectura de sensores."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data.user_crop_id, data.soil_moisture, data.air_temp, data.air_humidity, data.light, data.precipitation, data.wind_speed)
        )
        conn.commit()
        row_id = cur.lastrowid
        cur2 = conn.execute(
            "SELECT id, user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at "
            "FROM sensor_readings WHERE id = ?", (row_id,)
        )
        row = cur2.fetchone()
    cols = ["id", "user_crop_id", "soil_moisture", "air_temp", "air_humidity", "light", "precipitation", "wind_speed", "created_at"]
    return _row_to_dict(row, cols)


@router.get("/api/sensors/{user_crop_id}/latest", response_model=Optional[SensorOut])
async def latest_sensor(user_crop_id: int):
    """Última lectura de un cultivo."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id, user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at "
            "FROM sensor_readings WHERE user_crop_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_crop_id,)
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = ["id", "user_crop_id", "soil_moisture", "air_temp", "air_humidity", "light", "precipitation", "wind_speed", "created_at"]
    return _row_to_dict(row, cols)


# ───────── PARCELA (sensores agregados de todos los cultivos del usuario) ─────────
#
# Modelo conceptual:
#   - El productor tiene UNA parcela física.
#   - En la parcela hay varios cultivos, cada uno con su propio planted_at y ciclo.
#   - Los sensores son compartidos por la parcela; en BD viven en sensor_readings
#     por user_crop_id porque así fue diseñada la migración. La PARCELA se reconstruye
#     agregando todas las lecturas de los cultivos del usuario y, opcionalmente,
#     fusionando con edaphology_global_readings (observación general del predio).
#
# Endpoints derivados:
#   GET /api/parcel/latest/{user_id}             → última lectura agregada
#   GET /api/parcel/readings/{user_id}           → serie histórica diaria
#   GET /api/parcel/health/{user_id}             → salud agronómica (parcela ↔ cultivo)
# ──────────────────────────────────────────────────────────────────────────────


def _avg(values):
    real = [float(v) for v in values if v is not None]
    if not real:
        return None
    return sum(real) / len(real)


_TYPICAL_CYCLE_DEFAULT = 115


def _typical_cycle_days(crop_name: str) -> int:
    """
    Ciclo típico del cultivo (días).

    La lógica NO está hardcodeada por cultivo. Se lee desde `crop_profiles.cycle_days`
    (poblado por la migración 0013) usando coincidencia exacta o LIKE, y aplica un
    fallback si:
      - la columna no existe (BD antigua, antes de migración 0013), o
      - el cultivo no tiene perfil aún.

    Cualquier cultivo nuevo (Calabaza, papa, berenjena, …) se respeta sin tocar
    código: basta con un INSERT/UPDATE en `crop_profiles`.
    """
    name = (crop_name or "").strip().lower()
    if not name:
        return _TYPICAL_CYCLE_DEFAULT
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cycle_days FROM crop_profiles "
                "WHERE LOWER(crop_name) = ? OR LOWER(crop_name) LIKE ? "
                "ORDER BY (LOWER(crop_name) = ?) DESC LIMIT 1",
                (name, f"%{name}%", name),
            ).fetchone()
        if row and row[0] is not None:
            try:
                return max(15, int(row[0]))
            except (TypeError, ValueError):
                return _TYPICAL_CYCLE_DEFAULT
    except Exception as exc:
        logger.debug("crop_profiles.cycle_days no disponible: %s", exc)
    return _TYPICAL_CYCLE_DEFAULT


def _known_crop_names() -> List[str]:
    """
    Devuelve los cultivos que el sistema conoce, leyéndolos desde `crop_profiles`.
    Es la fuente de verdad dinámica que sustituye a las antiguas listas cerradas
    en código (`crop_aliases = ["maiz", "frijol", "calabaza", ...]`).
    """
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT LOWER(crop_name) FROM crop_profiles ORDER BY 1"
            ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        return []


def _phenological_stage(crop_name: str, planted_at: Optional[str]) -> Dict[str, Any]:
    """
    Determina la etapa fenológica aproximada del cultivo según días desde siembra
    y ciclo típico. Es una guía operativa, no un dato científico fino — se usa
    para enrutar consultas RAG por etapa.
    """
    cycle = _typical_cycle_days(crop_name)
    stage = "establecimiento"
    days = None
    progress_pct = None
    if planted_at:
        try:
            d0 = datetime.fromisoformat(str(planted_at)[:10])
            days = max(0, (datetime.now() - d0).days)
            progress_pct = min(100, round((days / cycle) * 100))
            if progress_pct < 18:
                stage = "establecimiento"
            elif progress_pct < 45:
                stage = "vegetativo"
            elif progress_pct < 70:
                stage = "floración"
            elif progress_pct < 90:
                stage = "fructificación"
            else:
                stage = "cosecha"
        except Exception:
            pass
    return {
        "stage": stage,
        "days_since_planting": days,
        "expected_progress_pct": progress_pct,
        "typical_cycle_days": cycle,
    }


def _aggregate_parcel_latest(conn, user_id: int) -> Dict[str, Any]:
    """
    Agrega la última lectura de cada cultivo del usuario y promedia.
    Si la parcela tiene edaphology_global_readings reciente, rellena huecos.
    """
    rows = conn.execute(
        """
        SELECT sr.soil_moisture, sr.air_temp, sr.air_humidity, sr.light,
               sr.precipitation, sr.wind_speed, sr.created_at
        FROM sensor_readings sr
        JOIN user_crops uc ON uc.id = sr.user_crop_id
        WHERE uc.user_id = ?
          AND sr.id IN (
            SELECT MAX(id) FROM sensor_readings
            GROUP BY user_crop_id
          )
        """,
        (user_id,),
    ).fetchall()

    soil = _avg([r[0] for r in rows])
    temp = _avg([r[1] for r in rows])
    hum = _avg([r[2] for r in rows])
    light = _avg([r[3] for r in rows])
    precip = _avg([r[4] for r in rows])
    wind = _avg([r[5] for r in rows])
    last_at = max([r[6] for r in rows], default=None) if rows else None

    glob = _get_latest_global_edaphology(conn) or {}
    if soil is None and glob.get("soil_moisture") is not None:
        soil = float(glob["soil_moisture"])
    if temp is None and glob.get("air_temp") is not None:
        temp = float(glob["air_temp"])
    if hum is None and glob.get("air_humidity") is not None:
        hum = float(glob["air_humidity"])
    if precip is None and glob.get("precipitation") is not None:
        precip = float(glob["precipitation"])
    if wind is None and glob.get("wind_speed") is not None:
        wind = float(glob["wind_speed"])
    if last_at is None and glob.get("created_at"):
        last_at = glob["created_at"]

    return {
        "user_id": user_id,
        "soil_moisture": soil,
        "air_temp": temp,
        "air_humidity": hum,
        "light": light,
        "precipitation": precip,
        "wind_speed": wind,
        "ph": glob.get("ph"),
        "conductivity": glob.get("conductivity"),
        "created_at": last_at,
        "sources": {
            "crop_sensor_streams": len(rows),
            "global_edaphology_used": bool(glob),
        },
    }


@router.get("/api/parcel/latest/{user_id}")
def parcel_latest(user_id: int):
    """Última lectura agregada de la parcela del usuario."""
    with get_conn() as conn:
        return _aggregate_parcel_latest(conn, user_id)


@router.get("/api/parcel/monitoring-guidelines")
def parcel_monitoring_guidelines():
    """
    Rangos agroambientales genéricos de parcela (JSON). Texto autoritativo paralelo en
    `parcel_micrometeorologia_general_milpa.txt` en biblioteca para RAG y para auditores humanos.
    """
    raw = _load_parcel_monitoring_guidelines()
    if not raw:
        raise HTTPException(status_code=500, detail="No se encontró parcel_micrometeorology_reference.json")
    raw["document_hint"] = "Biblioteca MILPA · parcel_micrometeorologia_general_milpa · combinar con crop_profiles cuando existan."
    return raw


@router.get("/api/parcel/readings/{user_id}")
def parcel_readings(
    user_id: int,
    since: Optional[str] = None,
    days: int = 120,
    limit: int = 240,
):
    """
    Serie histórica diaria de la parcela (promedio entre cultivos).

    - `since`: 'YYYY-MM-DD'. Si se provee, ignora `days` y filtra desde esa fecha.
    - `days`: ventana en días si no se da `since` (default 120).
    - `limit`: tope de filas devueltas (más reciente primero).
    """
    where_extra = ""
    params: List[Any] = [user_id]

    if since:
        where_extra = " AND date(sr.created_at) >= date(?)"
        params.append(since)
    elif days and days > 0:
        where_extra = " AND sr.created_at >= datetime('now', ?)"
        params.append(f"-{int(days)} day")

    sql = f"""
        SELECT date(sr.created_at) AS day,
               AVG(sr.soil_moisture)  AS soil_moisture,
               AVG(sr.air_temp)       AS air_temp,
               AVG(sr.air_humidity)   AS air_humidity,
               AVG(sr.light)          AS light,
               AVG(sr.precipitation)  AS precipitation,
               AVG(sr.wind_speed)     AS wind_speed,
               COUNT(*)               AS samples
        FROM sensor_readings sr
        JOIN user_crops uc ON uc.id = sr.user_crop_id
        WHERE uc.user_id = ?{where_extra}
        GROUP BY date(sr.created_at)
        ORDER BY day DESC
        LIMIT ?
    """
    params_with_limit = list(params) + [int(max(1, min(limit, 720)))]

    with get_conn() as conn:
        rows = conn.execute(sql, params_with_limit).fetchall()
        glob_rows = []
        if since:
            glob_rows = conn.execute(
                "SELECT date(created_at), air_temp, soil_moisture, air_humidity, precipitation "
                "FROM edaphology_global_readings WHERE date(created_at) >= date(?) "
                "ORDER BY created_at DESC LIMIT ?",
                (since, int(max(1, min(limit, 720)))),
            ).fetchall()

    days_data = []
    for r in rows:
        days_data.append({
            "day": r[0],
            "created_at": f"{r[0]}T12:00:00",
            "soil_moisture": r[1],
            "air_temp": r[2],
            "air_humidity": r[3],
            "light": r[4],
            "precipitation": r[5],
            "wind_speed": r[6],
            "samples": r[7],
            "source": "parcel_aggregate",
        })

    if glob_rows:
        existing_days = {d["day"] for d in days_data}
        for g in glob_rows:
            day = g[0]
            if day in existing_days:
                continue
            days_data.append({
                "day": day,
                "created_at": f"{day}T12:00:00",
                "soil_moisture": g[2],
                "air_temp": g[1],
                "air_humidity": g[3],
                "precipitation": g[4],
                "samples": 0,
                "source": "edaphology_global",
            })

    days_data.sort(key=lambda x: x["day"])
    return {
        "user_id": user_id,
        "since": since,
        "window_days": days,
        "count": len(days_data),
        "rows": days_data,
    }


def _evaluate_crop_health(
    crop: Dict[str, Any],
    parcel_latest: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evalúa la salud de UN cultivo cruzando:
      - Última telemetría agregada de la PARCELA (humedad suelo, temperatura, etc.)
      - El perfil agronómico de referencia del cultivo (crop_profiles)
      - El ritmo fenológico (días desde planted_at vs ciclo típico) — penaliza
        cultivos cuyo `progress` reportado va muy por detrás del esperado.

    Devuelve label en {Saludable, Vigilancia, Crítico, Establecimiento}, score 0-100,
    factores con su severidad y un resumen de fuentes.
    """
    pheno = _phenological_stage(crop.get("crop_name") or "", crop.get("planted_at"))

    soil = parcel_latest.get("soil_moisture")
    temp = parcel_latest.get("air_temp")
    hum = parcel_latest.get("air_humidity")
    score = 100
    factors: List[Dict[str, Any]] = []

    if profile:
        sm_min = profile.get("optimal_soil_moisture_min") or 35
        sm_max = profile.get("optimal_soil_moisture_max") or 75
        t_min = profile.get("optimal_temp_min") or 12
        t_max = profile.get("optimal_temp_max") or 33
        h_min = profile.get("optimal_air_humidity_min") or 40
        h_max = profile.get("optimal_air_humidity_max") or 90
    else:
        sm_min, sm_max, t_min, t_max, h_min, h_max = 35, 75, 12, 33, 40, 90

    if soil is None and temp is None:
        factors.append({"code": "sin_telemetria", "severity": "info",
                        "message": "Parcela sin lecturas recientes; se requiere monitoreo activo."})
        score -= 15

    if soil is not None:
        if soil < sm_min - 12:
            score -= 38
            factors.append({"code": "agua_critica", "severity": "high",
                            "message": f"Humedad de suelo en parcela {soil:.0f}% (mínimo del cultivo {sm_min:.0f}%)."})
        elif soil < sm_min:
            score -= 18
            factors.append({"code": "agua_baja", "severity": "medium",
                            "message": f"Humedad de suelo {soil:.0f}% por debajo del óptimo del cultivo."})
        elif soil > sm_max + 10:
            score -= 18
            factors.append({"code": "agua_excesiva", "severity": "medium",
                            "message": f"Humedad de suelo alta ({soil:.0f}%); riesgo de encharcamiento."})

    if temp is not None:
        if temp >= t_max + 4:
            score -= 35
            factors.append({"code": "calor_extremo", "severity": "high",
                            "message": f"Temperatura aire {temp:.0f}°C (máxima cultivo {t_max:.0f}°C)."})
        elif temp > t_max:
            score -= 15
            factors.append({"code": "calor", "severity": "medium",
                            "message": f"Temperatura por encima del óptimo del cultivo ({temp:.0f}°C)."})
        elif temp < t_min - 2:
            score -= 25
            factors.append({"code": "frio", "severity": "high",
                            "message": f"Temperatura baja ({temp:.0f}°C); revisar protección térmica."})

    if hum is not None:
        if hum < h_min - 15:
            score -= 12
            factors.append({"code": "aire_seco", "severity": "low",
                            "message": f"Humedad relativa baja ({hum:.0f}%)."})
        elif hum > h_max + 5:
            score -= 10
            factors.append({"code": "aire_humedo", "severity": "low",
                            "message": f"Humedad relativa alta ({hum:.0f}%); riesgo fungoso."})

    expected_pct = pheno.get("expected_progress_pct")
    progress_reported = int(crop.get("progress") or 0)
    if expected_pct is not None and pheno.get("days_since_planting") is not None:
        lag = progress_reported - expected_pct
        if lag < -35:
            score -= 28
            factors.append({"code": "fenologia_atrasada", "severity": "high",
                            "message": f"Avance reportado {progress_reported}% vs esperado ~{expected_pct}% (día {pheno['days_since_planting']} del ciclo)."})
        elif lag < -18:
            score -= 14
            factors.append({"code": "fenologia_rezaga", "severity": "medium",
                            "message": "Posible rezago fenológico respecto al tiempo desde siembra."})

    score = max(0, min(100, round(score)))
    severe = any(f["severity"] == "high" for f in factors)

    if pheno.get("days_since_planting") is not None and pheno["days_since_planting"] < 21 and not severe:
        label = "Establecimiento"
    elif score >= 72 and not severe:
        label = "Saludable"
    elif score >= 48:
        label = "Vigilancia"
    elif score >= 28:
        label = "Crítico"
    else:
        label = "Crítico" if severe else "Establecimiento"

    summary = " ".join(f["message"] for f in factors) or \
              "Parcela dentro de los rangos del cultivo y ritmo coherente con el ciclo."

    return {
        "crop_id": crop.get("id"),
        "crop_name": crop.get("crop_name"),
        "display_name": crop.get("display_name"),
        "planted_at": crop.get("planted_at"),
        "progress": progress_reported,
        "label": label,
        "score": score,
        "factors": factors,
        "summary": summary,
        "phenology": pheno,
        # Umbrales realmente usados al evaluar este cultivo. El dashboard los
        # consume para construir alertas globales sin hardcodear (ej. techo
        # térmico = min(optimal_temp_max) entre cultivos activos).
        "profile_used": {
            "optimal_soil_moisture_min": sm_min,
            "optimal_soil_moisture_max": sm_max,
            "optimal_temp_min": t_min,
            "optimal_temp_max": t_max,
            "optimal_air_humidity_min": h_min,
            "optimal_air_humidity_max": h_max,
            "from_crop_profiles": profile is not None,
        },
        "evaluated_with": {
            "parcel_latest_at": parcel_latest.get("created_at"),
            "uses_parcel_telemetry": parcel_latest.get("created_at") is not None,
            "uses_crop_profile": profile is not None,
        },
    }


@router.get("/api/parcel/health/{user_id}")
def parcel_health(user_id: int):
    """
    Salud agronómica del usuario:
      - Telemetría: agregado de la parcela (todos los cultivos + edafología global).
      - Por cultivo: cruza la lectura parcela con el perfil agronómico del cultivo
        (crop_profiles) y con el ritmo fenológico desde planted_at.
    """
    with get_conn() as conn:
        parcel = _aggregate_parcel_latest(conn, user_id)
        crops = conn.execute(
            "SELECT id, user_id, crop_name, display_name, variety, planted_at, "
            "expected_harvest_at, growth_stage, image_path, status, progress, notes, created_at "
            "FROM user_crops WHERE user_id = ? AND status = 'activo' ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        crop_cols = ["id", "user_id", "crop_name", "display_name", "variety", "planted_at",
                     "expected_harvest_at", "growth_stage", "image_path", "status", "progress",
                     "notes", "created_at"]
        crops_dicts = [_row_to_dict(r, crop_cols) for r in crops]

        profiles_by_name: Dict[str, Dict[str, Any]] = {}
        for c in crops_dicts:
            cn = (c.get("crop_name") or "").lower()
            if cn in profiles_by_name:
                continue
            row = conn.execute(
                "SELECT id, crop_name, variety, optimal_temp_min, optimal_temp_max, "
                "optimal_soil_moisture_min, optimal_soil_moisture_max, optimal_air_humidity_min, "
                "optimal_air_humidity_max, optimal_ph_min, optimal_ph_max, notes, created_at, updated_at "
                "FROM crop_profiles WHERE crop_name = ? LIMIT 1",
                (cn,),
            ).fetchone()
            if row:
                profiles_by_name[cn] = _row_to_dict(row, [
                    "id", "crop_name", "variety", "optimal_temp_min", "optimal_temp_max",
                    "optimal_soil_moisture_min", "optimal_soil_moisture_max", "optimal_air_humidity_min",
                    "optimal_air_humidity_max", "optimal_ph_min", "optimal_ph_max", "notes",
                    "created_at", "updated_at",
                ])

    items = [
        _evaluate_crop_health(c, parcel, profiles_by_name.get((c.get("crop_name") or "").lower()))
        for c in crops_dicts
    ]
    return {
        "user_id": user_id,
        "parcel_latest": parcel,
        "crops": items,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ───────── BASE EDAFOLÓGICA GLOBAL ─────────

@router.get("/api/edaphology/global/latest", response_model=Optional[GlobalEdaphologyOut])
async def latest_global_edaphology():
    """Retorna la lectura edafológica global más reciente (afecta a todos los cultivos)."""
    with get_conn() as conn:
        return _get_latest_global_edaphology(conn)


@router.post("/api/edaphology/global", response_model=GlobalEdaphologyOut, status_code=201)
async def create_global_edaphology(data: GlobalEdaphologyCreate):
    """Registra una nueva lectura edafológica general del predio/zona."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO edaphology_global_readings "
            "(location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.location_name or "general",
                data.soil_temp,
                data.air_temp,
                data.air_humidity,
                data.soil_moisture,
                data.precipitation,
                data.wind_speed,
                data.ph,
                data.conductivity,
                data.notes,
            )
        )
        conn.commit()
        row_id = cur.lastrowid
        cur2 = conn.execute(
            "SELECT id, location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes, created_at "
            "FROM edaphology_global_readings WHERE id = ?", (row_id,)
        )
        row = cur2.fetchone()

    cols = [
        "id", "location_name", "soil_temp", "air_temp", "air_humidity", "soil_moisture",
        "precipitation", "wind_speed", "ph", "conductivity", "notes", "created_at"
    ]
    return _row_to_dict(row, cols)


@router.patch("/api/edaphology/global/latest", response_model=GlobalEdaphologyOut)
async def patch_latest_global_edaphology(body: GlobalEdaphologyUpdate):
    """Actualiza el registro edafológico global más reciente (mismo `id` en SQLite)."""
    cols = [
        "id", "location_name", "soil_temp", "air_temp", "air_humidity", "soil_moisture",
        "precipitation", "wind_speed", "ph", "conductivity", "notes", "created_at",
    ]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, location_name, soil_temp, air_temp, air_humidity, soil_moisture, "
            "precipitation, wind_speed, ph, conductivity, notes, created_at "
            "FROM edaphology_global_readings ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="No hay lectura edafológica global; usa POST /api/edaphology/global primero.",
            )
        existing = _row_to_dict(row, cols)
        merged = _merge_validate_global_edaphology(existing, body)
        conn.execute(
            "UPDATE edaphology_global_readings SET location_name=?, soil_temp=?, air_temp=?, air_humidity=?, "
            "soil_moisture=?, precipitation=?, wind_speed=?, ph=?, conductivity=?, notes=? WHERE id=?",
            (
                merged.get("location_name"),
                merged.get("soil_temp"),
                merged.get("air_temp"),
                merged.get("air_humidity"),
                merged.get("soil_moisture"),
                merged.get("precipitation"),
                merged.get("wind_speed"),
                merged.get("ph"),
                merged.get("conductivity"),
                merged.get("notes"),
                int(existing["id"]),
            ),
        )
        conn.commit()
        row2 = conn.execute(
            "SELECT id, location_name, soil_temp, air_temp, air_humidity, soil_moisture, "
            "precipitation, wind_speed, ph, conductivity, notes, created_at "
            "FROM edaphology_global_readings WHERE id=?",
            (int(existing["id"]),),
        ).fetchone()
    return _row_to_dict(row2, cols)


@router.get("/api/known-crops")
def list_known_crops():
    """
    Catálogo dinámico de cultivos que el sistema reconoce. Lee `crop_profiles`
    y devuelve `[{crop_name, variety, cycle_days, optimal_*}]`. Sustituye a
    las listas cerradas que vivían en código y permite que cualquier cultivo
    nuevo (incluyendo el caso de prueba "Calabaza") aparezca sin redeploy.
    """
    cols_basic = [
        "crop_name", "variety", "optimal_temp_min", "optimal_temp_max",
        "optimal_soil_moisture_min", "optimal_soil_moisture_max",
        "optimal_air_humidity_min", "optimal_air_humidity_max",
        "optimal_ph_min", "optimal_ph_max", "notes",
    ]
    select_clause = ", ".join(cols_basic)
    rows: List[tuple] = []
    has_cycle = False
    with get_conn() as conn:
        # Detección defensiva: si la migración 0013 todavía no se aplicó,
        # `cycle_days` no existe; en ese caso devolvemos los demás campos y
        # marcamos `cycle_days = null` en la respuesta.
        try:
            rows = conn.execute(
                f"SELECT {select_clause}, cycle_days FROM crop_profiles ORDER BY crop_name"
            ).fetchall()
            has_cycle = True
        except Exception:
            rows = conn.execute(
                f"SELECT {select_clause} FROM crop_profiles ORDER BY crop_name"
            ).fetchall()
    out = []
    for row in rows:
        record = dict(zip(cols_basic, row[: len(cols_basic)]))
        record["cycle_days"] = (row[len(cols_basic)] if has_cycle else None)
        out.append(record)
    return out


def _table_has_column(conn, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def _clamp_opt_float(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valor numérico inválido")
    return max(lo, min(hi, x))


def _clamp_opt_int(v: Optional[int], lo: int, hi: int) -> Optional[int]:
    if v is None:
        return None
    try:
        x = int(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valor entero inválido")
    return max(lo, min(hi, x))


def _sanitize_notes(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:2000] if len(s) > 2000 else s


def _merge_validate_global_edaphology(existing: Dict[str, Any], patch: GlobalEdaphologyUpdate) -> Dict[str, Any]:
    """Fusiona PATCH sobre el registro vigente y acota rangos físicos plausibles."""
    d = dict(existing)
    raw = patch.model_dump(exclude_unset=True)
    if not raw:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    for k, v in raw.items():
        if k == "location_name":
            d[k] = (str(v).strip()[:200] if v is not None else "general") or "general"
        elif k == "notes":
            d[k] = _sanitize_notes(v)
        elif k == "soil_temp":
            d[k] = _clamp_opt_float(v, -40.0, 60.0)
        elif k == "air_temp":
            d[k] = _clamp_opt_float(v, -40.0, 60.0)
        elif k in ("air_humidity", "soil_moisture"):
            d[k] = _clamp_opt_float(v, 0.0, 100.0)
        elif k == "precipitation":
            d[k] = _clamp_opt_float(v, 0.0, 500.0)
        elif k == "wind_speed":
            d[k] = _clamp_opt_float(v, 0.0, 200.0)
        elif k == "ph":
            d[k] = _clamp_opt_float(v, 0.0, 14.0)
        elif k == "conductivity":
            d[k] = _clamp_opt_float(v, 0.0, 50.0)
    return d


def _merge_validate_crop_profile_row(existing: Dict[str, Any], patch: CropProfileUpdate) -> Dict[str, Any]:
    """Fusiona patch sobre existing y aplica límites agronómicos plausibles."""
    d = dict(existing)
    raw = patch.model_dump(exclude_unset=True)
    for k, v in raw.items():
        if k == "variety":
            d[k] = (str(v).strip()[:200] if v is not None else None)
        elif k == "notes":
            d[k] = _sanitize_notes(v)
        elif k == "cycle_days":
            d[k] = _clamp_opt_int(v, 15, 400)
        elif k.startswith("optimal_"):
            if k.endswith(("_min", "_max")):
                if "temp" in k:
                    d[k] = _clamp_opt_float(v, -40.0, 60.0)
                elif "moisture" in k or "humidity" in k:
                    d[k] = _clamp_opt_float(v, 0.0, 100.0)
                elif "ph" in k:
                    d[k] = _clamp_opt_float(v, 0.0, 14.0)
                else:
                    d[k] = v
    # Coherencia min <= max
    smin, smax = d.get("optimal_soil_moisture_min"), d.get("optimal_soil_moisture_max")
    if smin is not None and smax is not None and smin > smax:
        raise HTTPException(status_code=400, detail="optimal_soil_moisture_min no puede ser mayor que max")
    tmin, tmax = d.get("optimal_temp_min"), d.get("optimal_temp_max")
    if tmin is not None and tmax is not None and tmin > tmax:
        raise HTTPException(status_code=400, detail="optimal_temp_min no puede ser mayor que max")
    hmin, hmax = d.get("optimal_air_humidity_min"), d.get("optimal_air_humidity_max")
    if hmin is not None and hmax is not None and hmin > hmax:
        raise HTTPException(status_code=400, detail="optimal_air_humidity_min no puede ser mayor que max")
    phmin, phmax = d.get("optimal_ph_min"), d.get("optimal_ph_max")
    if phmin is not None and phmax is not None and phmin > phmax:
        raise HTTPException(status_code=400, detail="optimal_ph_min no puede ser mayor que max")
    return d


@router.get("/api/edaphology/crop-profile/{crop_name}", response_model=Optional[CropProfileOut])
async def get_crop_profile(crop_name: str):
    """Retorna el perfil agronómico base de un cultivo para contextualizar recomendaciones."""
    with get_conn() as conn:
        has_cd = _table_has_column(conn, "crop_profiles", "cycle_days")
        sel = (
            "SELECT id, crop_name, variety, optimal_temp_min, optimal_temp_max, optimal_soil_moisture_min, "
            "optimal_soil_moisture_max, optimal_air_humidity_min, optimal_air_humidity_max, optimal_ph_min, "
            "optimal_ph_max, notes, created_at, updated_at"
            + (", cycle_days" if has_cd else "")
            + " FROM crop_profiles WHERE crop_name = ?"
        )
        cur = conn.execute(sel, (crop_name.lower(),))
        row = cur.fetchone()
    if not row:
        return None
    cols = [
        "id", "crop_name", "variety", "optimal_temp_min", "optimal_temp_max", "optimal_soil_moisture_min",
        "optimal_soil_moisture_max", "optimal_air_humidity_min", "optimal_air_humidity_max", "optimal_ph_min",
        "optimal_ph_max", "notes", "created_at", "updated_at",
    ]
    if has_cd:
        cols.append("cycle_days")
    out = _row_to_dict(row, cols)
    if not has_cd:
        out["cycle_days"] = None
    return out


@router.patch("/api/edaphology/crop-profile/{crop_name}", response_model=CropProfileOut)
async def patch_crop_profile(crop_name: str, body: CropProfileUpdate):
    """Actualiza rangos óptimos del cultivo en `crop_profiles` con validación server-side."""
    cn = crop_name.lower().strip()
    if not cn:
        raise HTTPException(status_code=400, detail="crop_name vacío")
    if not body.model_dump(exclude_unset=True):
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, crop_name, variety, optimal_temp_min, optimal_temp_max, optimal_soil_moisture_min, "
            "optimal_soil_moisture_max, optimal_air_humidity_min, optimal_air_humidity_max, optimal_ph_min, "
            "optimal_ph_max, notes, created_at, updated_at "
            "FROM crop_profiles WHERE crop_name = ?",
            (cn,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Perfil no encontrado")
        cols0 = [
            "id", "crop_name", "variety", "optimal_temp_min", "optimal_temp_max", "optimal_soil_moisture_min",
            "optimal_soil_moisture_max", "optimal_air_humidity_min", "optimal_air_humidity_max", "optimal_ph_min",
            "optimal_ph_max", "notes", "created_at", "updated_at",
        ]
        existing = _row_to_dict(row, cols0)
        merged = _merge_validate_crop_profile_row(existing, body)
        has_cd = _table_has_column(conn, "crop_profiles", "cycle_days")
        patch_keys = body.model_dump(exclude_unset=True)
        conn.execute(
            "UPDATE crop_profiles SET variety=?, optimal_temp_min=?, optimal_temp_max=?, "
            "optimal_soil_moisture_min=?, optimal_soil_moisture_max=?, optimal_air_humidity_min=?, "
            "optimal_air_humidity_max=?, optimal_ph_min=?, optimal_ph_max=?, notes=?, "
            "updated_at=datetime('now') WHERE crop_name=?",
            (
                merged.get("variety"),
                merged.get("optimal_temp_min"),
                merged.get("optimal_temp_max"),
                merged.get("optimal_soil_moisture_min"),
                merged.get("optimal_soil_moisture_max"),
                merged.get("optimal_air_humidity_min"),
                merged.get("optimal_air_humidity_max"),
                merged.get("optimal_ph_min"),
                merged.get("optimal_ph_max"),
                merged.get("notes"),
                cn,
            ),
        )
        if has_cd and "cycle_days" in patch_keys:
            conn.execute(
                "UPDATE crop_profiles SET cycle_days=?, updated_at=datetime('now') WHERE crop_name=?",
                (merged.get("cycle_days"), cn),
            )
        conn.commit()
    # Devolver fila actualizada (con cycle_days si existe)
    return await get_crop_profile(cn)  # type: ignore


@router.get("/api/dataset/snapshot")
async def dataset_snapshot(user_id: int):
    """
    Vista consolidada del dataset operativo para paneles de administración local:
    lectura parcela agregada, última edafología global, cultivos del usuario y catálogo de perfiles.
    """
    with get_conn() as conn:
        parcel = _aggregate_parcel_latest(conn, user_id)
        glob = _get_latest_global_edaphology(conn)
        crop_rows = conn.execute(
            "SELECT id, user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, "
            "growth_stage, status, progress FROM user_crops WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
        cc = [
            "id", "user_id", "crop_name", "display_name", "variety", "planted_at",
            "expected_harvest_at", "growth_stage", "status", "progress",
        ]
        user_crops = [_row_to_dict(r, cc) for r in crop_rows]
    catalog = list_known_crops()
    return {
        "user_id": user_id,
        "parcel_latest": parcel,
        "global_edaphology": glob,
        "user_crops": user_crops,
        "crop_profiles_catalog": catalog,
    }


@router.post("/api/dataset/apply-sensor-reading")
async def dataset_apply_sensor_reading(data: DatasetApplySensorIn):
    """
    Inserta lecturas validadas en `sensor_readings`. Replica en todos los cultivos activos del usuario
    si no se indica `user_crop_id` (comportamiento típico de parcela única con varios cultivos).
    """
    vals = {
        "soil_moisture": _clamp_opt_float(data.soil_moisture, 0.0, 100.0),
        "air_temp": _clamp_opt_float(data.air_temp, -40.0, 60.0),
        "air_humidity": _clamp_opt_float(data.air_humidity, 0.0, 100.0),
        "light": _clamp_opt_float(data.light, 0.0, 100.0),
        "precipitation": _clamp_opt_float(data.precipitation, 0.0, 500.0),
        "wind_speed": _clamp_opt_float(data.wind_speed, 0.0, 200.0),
    }
    if all(v is None for v in vals.values()):
        raise HTTPException(status_code=400, detail="Indica al menos un campo de sensor")
    with get_conn() as conn:
        if data.user_crop_id is not None:
            row = conn.execute(
                "SELECT id FROM user_crops WHERE id=? AND user_id=?",
                (data.user_crop_id, data.user_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cultivo no encontrado para este usuario")
            targets = [int(data.user_crop_id)]
        else:
            targets = [
                int(r[0])
                for r in conn.execute(
                    "SELECT id FROM user_crops WHERE user_id=? AND COALESCE(status,'activo')='activo'",
                    (data.user_id,),
                ).fetchall()
            ]
        if not targets:
            raise HTTPException(status_code=400, detail="No hay cultivos activos para este usuario")
        inserted = []
        for uc_id in targets:
            cur = conn.execute(
                "INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, "
                "light, precipitation, wind_speed) VALUES (?,?,?,?,?,?,?)",
                (
                    uc_id,
                    vals["soil_moisture"],
                    vals["air_temp"],
                    vals["air_humidity"],
                    vals["light"],
                    vals["precipitation"],
                    vals["wind_speed"],
                ),
            )
            rid = cur.lastrowid
            row2 = conn.execute(
                "SELECT id, user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, "
                "wind_speed, created_at FROM sensor_readings WHERE id=?",
                (rid,),
            ).fetchone()
            inserted.append(
                _row_to_dict(
                    row2,
                    [
                        "id", "user_crop_id", "soil_moisture", "air_temp", "air_humidity",
                        "light", "precipitation", "wind_speed", "created_at",
                    ],
                )
            )
        conn.commit()
    return {
        "ok": True,
        "inserted_count": len(inserted),
        "user_crop_ids": targets,
        "readings": inserted,
        "values_applied": vals,
    }


# ───────── QUERY BUILDER: sensor data → RAG query ─────────

# Umbrales de respaldo cuando el cultivo no tiene perfil agronómico aún. NO
# son por cultivo: son agronómicamente conservadores y solo aplican si la
# tabla `crop_profiles` no devuelve filas. Cualquier cultivo registrado en
# esa tabla anula automáticamente estos defaults.
_FALLBACK_BOUNDS = {
    "soil_min": 35.0, "soil_max": 80.0,
    "temp_min": 12.0, "temp_max": 33.0,
    "hum_min":  40.0, "hum_max":  85.0,
    # Umbral de calor extremo independiente del cultivo (regla del prompt
    # técnico: 55 °C dispara emergencia). Es un umbral global de seguridad
    # operativa, no una regla por cultivo.
    "extreme_heat": 55.0,
    # Severidad: cuánto por debajo del mínimo es "crítico" (margen).
    "soil_critical_margin": 10.0,
    "temp_severe_margin": 5.0,
}


def _resolve_bounds(profile: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """
    Devuelve los umbrales operativos a usar para clasificar una lectura.
    Si el cultivo tiene perfil en `crop_profiles` se usan sus rangos; si no,
    se cae a `_FALLBACK_BOUNDS`. Esto sustituye a los `if temp >= 35` fijos.
    """
    fb = _FALLBACK_BOUNDS
    p = profile or {}
    return {
        "soil_min": float(p.get("optimal_soil_moisture_min") or fb["soil_min"]),
        "soil_max": float(p.get("optimal_soil_moisture_max") or fb["soil_max"]),
        "temp_min": float(p.get("optimal_temp_min") or fb["temp_min"]),
        "temp_max": float(p.get("optimal_temp_max") or fb["temp_max"]),
        "hum_min":  float(p.get("optimal_air_humidity_min") or fb["hum_min"]),
        "hum_max":  float(p.get("optimal_air_humidity_max") or fb["hum_max"]),
        "extreme_heat": float(fb["extreme_heat"]),
        "soil_critical_margin": float(fb["soil_critical_margin"]),
        "temp_severe_margin": float(fb["temp_severe_margin"]),
    }


def build_recommendation_query(crop_name: str, sensor: dict, profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Transforma datos de sensor + cultivo en una consulta RAG optimizada.
    Genera una pregunta en lenguaje natural rica en términos agrícolas.
    Si el cultivo tiene perfil agronómico, los rangos se leen desde
    `crop_profiles` para que la query refleje la realidad del cultivo.
    """
    b = _resolve_bounds(profile)
    parts = [f"recomendaciones para cultivo de {crop_name}"]

    sm = sensor.get("soil_moisture")
    if sm is not None:
        if sm < b["soil_min"]:
            parts.append(
                f"humedad del suelo baja ({sm:.0f}%) por debajo del mínimo del cultivo "
                f"({b['soil_min']:.0f}%) requiere riego inmediato"
            )
        elif sm > b["soil_max"]:
            parts.append(
                f"humedad del suelo excesiva ({sm:.0f}%) por encima del máximo "
                f"({b['soil_max']:.0f}%) riesgo encharcamiento"
            )
        else:
            parts.append(f"humedad del suelo {sm:.0f}%")

    temp = sensor.get("air_temp")
    if temp is not None:
        if temp >= b["extreme_heat"]:
            parts.append(
                f"temperatura extrema ({temp:.0f}°C) calor crítico activar alerta "
                "de calor extremo y medidas de emergencia"
            )
        elif temp > b["temp_max"]:
            parts.append(
                f"temperatura alta ({temp:.0f}°C) por encima del máximo del cultivo "
                f"({b['temp_max']:.0f}°C) estrés térmico riesgo de aborto floral"
            )
        elif temp < b["temp_min"]:
            parts.append(
                f"temperatura baja ({temp:.0f}°C) por debajo del mínimo "
                f"({b['temp_min']:.0f}°C) riesgo helada"
            )
        else:
            parts.append(f"temperatura {temp:.0f}°C")

    hum = sensor.get("air_humidity")
    if hum is not None:
        if hum < b["hum_min"]:
            parts.append(
                f"humedad ambiental baja ({hum:.0f}%) por debajo del mínimo "
                f"({b['hum_min']:.0f}%) riesgo deshidratación reducir estrés hídrico"
            )
        elif hum > b["hum_max"]:
            parts.append(
                f"humedad ambiental alta ({hum:.0f}%) por encima del máximo "
                f"({b['hum_max']:.0f}%) riesgo enfermedades fúngicas"
            )
        else:
            parts.append(f"humedad aire {hum:.0f}%")

    light = sensor.get("light")
    if light is not None:
        if light < 20:
            parts.append("baja luminosidad")
        elif light > 90:
            parts.append("alta radiación solar")

    precip = sensor.get("precipitation")
    if precip is not None and precip > 0:
        parts.append(f"precipitación reciente {precip:.1f}mm")

    return ". ".join(parts)


def classify_action(query: str, crop_name: str, sensor: dict, profile: Optional[Dict[str, Any]] = None) -> tuple:
    """
    Clasifica la acción principal y la prioridad basada en la lectura del
    sensor cruzada con el perfil agronómico del cultivo. Si el cultivo no
    tiene perfil aún, los defaults del módulo aplican (sin hardcoding por
    nombre de cultivo).

    Resultado: (action, priority).
    """
    b = _resolve_bounds(profile)
    sm = sensor.get("soil_moisture")
    temp = sensor.get("air_temp")
    hum = sensor.get("air_humidity")

    # Calor extremo: regla global de seguridad (>=55 °C por defecto).
    if temp is not None and temp >= b["extreme_heat"]:
        return "alerta de calor extremo y medidas de emergencia", "high"

    # Sequía severa: humedad del suelo muy por debajo del mínimo del cultivo.
    if sm is not None and sm < (b["soil_min"] - b["soil_critical_margin"]):
        return "riego urgente", "high"

    # Calor severo: temperatura por encima del máximo + margen.
    if temp is not None and temp >= (b["temp_max"] + b["temp_severe_margin"]):
        return "proteger del calor", "high"

    # Riesgo fúngico por humedad relativa muy alta.
    if hum is not None and hum > (b["hum_max"] + 5):
        return "vigilar enfermedades fúngicas", "high"

    # Sequía moderada.
    if sm is not None and sm < b["soil_min"]:
        return "programar riego", "medium"

    # Calor moderado.
    if temp is not None and temp > b["temp_max"]:
        return "sombra o acolchado", "medium"

    # Suelo por encima del óptimo antes que “aire seco”: prioridad suelo para decisiones de riego.
    if sm is not None and sm > b["soil_max"]:
        return "drenar exceso de agua", "medium"

    # Aire muy seco (no priorizar riego foliar si el suelo ya está empapado; cubierto arriba).
    if hum is not None and hum < b["hum_min"]:
        return "riego foliar", "medium"

    return "monitoreo continuo", "low"


# ───────── RECOMENDACIONES ENDPOINT ─────────

@router.get("/api/recommendations/{user_crop_id}", response_model=List[RecommendationOut])
async def list_recommendations(user_crop_id: int, status: Optional[str] = None):
    """Lista recomendaciones de un cultivo, opcionalmente filtradas por estado."""
    query = "SELECT id, user_crop_id, query_text, action, priority, detail_html, citations, status, faithfulness, created_at FROM recommendations WHERE user_crop_id = ?"
    params: list = [user_crop_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
    cols = ["id", "user_crop_id", "query_text", "action", "priority", "detail_html", "citations", "status", "faithfulness", "created_at"]
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/api/recommendations/user/{user_id}", response_model=List[RecommendationOut])
async def list_user_recommendations(user_id: int, status: Optional[str] = None, crop: Optional[str] = None, action_type: Optional[str] = None):
    """Lista todas las recomendaciones de todos los cultivos de un usuario."""
    query = (
        "SELECT r.id, r.user_crop_id, r.query_text, r.action, r.priority, r.detail_html, "
        "r.citations, r.status, r.faithfulness, r.created_at "
        "FROM recommendations r JOIN user_crops uc ON r.user_crop_id = uc.id "
        "WHERE uc.user_id = ?"
    )
    params: list = [user_id]
    if status and status != "todos":
        query += " AND r.status = ?"
        params.append(status)
    if crop and crop != "todos":
        query += " AND uc.crop_name = ?"
        params.append(crop)
    if action_type and action_type != "todos":
        query += " AND r.action LIKE ?"
        params.append(f"%{action_type}%")
    query += " ORDER BY r.created_at DESC"
    with get_conn() as conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
    cols = ["id", "user_crop_id", "query_text", "action", "priority", "detail_html", "citations", "status", "faithfulness", "created_at"]
    return [_row_to_dict(r, cols) for r in rows]


@router.patch("/api/recommendations/{rec_id}/status")
async def update_recommendation_status(rec_id: int, data: RecommendationUpdateStatus):
    """Actualiza el estado de una recomendación (pendiente → aplicada / pospuesta)."""
    if data.status not in ("pendiente", "aplicada", "pospuesta"):
        raise HTTPException(400, "Estado inválido")
    with get_conn() as conn:
        conn.execute("UPDATE recommendations SET status = ? WHERE id = ?", (data.status, rec_id))
        conn.commit()
    return {"ok": True, "id": rec_id, "status": data.status}


@router.post("/api/recommendations/generate", response_model=RecommendationOut)
async def generate_recommendation(req: RecommendationRequest):
    """
    Pipeline completo: toma datos de sensor del cultivo, construye query RAG,
    ejecuta búsqueda híbrida, genera respuesta con citas, y guarda la recomendación.
    """
    # 1) Obtener cultivo y última lectura de sensor
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id, crop_name, variety FROM user_crops WHERE id = ?",
            (req.user_crop_id,)
        )
        crop_row = cur.fetchone()
        if not crop_row:
            raise HTTPException(404, "Cultivo no encontrado")
        crop_id, crop_name, variety = crop_row

        cur2 = conn.execute(
            "SELECT soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed "
            "FROM sensor_readings WHERE user_crop_id = ? ORDER BY created_at DESC LIMIT 1",
            (req.user_crop_id,)
        )
        sensor_row = cur2.fetchone()

        global_edaphology = _get_latest_global_edaphology(conn)

        cur3 = conn.execute(
            "SELECT id, crop_name, variety, optimal_temp_min, optimal_temp_max, optimal_soil_moisture_min, "
            "optimal_soil_moisture_max, optimal_air_humidity_min, optimal_air_humidity_max, optimal_ph_min, "
            "optimal_ph_max, notes, created_at, updated_at "
            "FROM crop_profiles WHERE crop_name = ?",
            (crop_name.lower(),)
        )
        profile_row = cur3.fetchone()

    if not sensor_row:
        raise HTTPException(404, "No hay lecturas de sensor para este cultivo")

    sensor = {
        "soil_moisture": sensor_row[0],
        "air_temp": sensor_row[1],
        "air_humidity": sensor_row[2],
        "light": sensor_row[3],
        "precipitation": sensor_row[4],
        "wind_speed": sensor_row[5],
    }

    # Precedencia: sensores del cultivo (parcela) > estación regional / edafología global.
    # Solo se rellenan huecos con la lectura global; no sobrescribir la parcela.
    if global_edaphology:
        if sensor.get("air_temp") is None and global_edaphology.get("air_temp") is not None:
            sensor["air_temp"] = global_edaphology["air_temp"]
        if sensor.get("air_humidity") is None and global_edaphology.get("air_humidity") is not None:
            sensor["air_humidity"] = global_edaphology["air_humidity"]
        if sensor.get("precipitation") is None and global_edaphology.get("precipitation") is not None:
            sensor["precipitation"] = global_edaphology["precipitation"]
        if sensor.get("wind_speed") is None and global_edaphology.get("wind_speed") is not None:
            sensor["wind_speed"] = global_edaphology["wind_speed"]

    profile = None
    if profile_row:
        profile_cols = [
            "id", "crop_name", "variety", "optimal_temp_min", "optimal_temp_max", "optimal_soil_moisture_min",
            "optimal_soil_moisture_max", "optimal_air_humidity_min", "optimal_air_humidity_max", "optimal_ph_min",
            "optimal_ph_max", "notes", "created_at", "updated_at"
        ]
        profile = _row_to_dict(profile_row, profile_cols)

    # 2) Construir query inteligente. La función ya consume el perfil del
    # cultivo si está disponible para parametrizar los umbrales por
    # `crop_profiles` en lugar de números fijos.
    rag_query = build_recommendation_query(crop_name, sensor, profile)
    if profile:
        rag_query += (
            f". rango óptimo de temperatura {profile.get('optimal_temp_min')} a {profile.get('optimal_temp_max')}°C"
            f". rango óptimo de humedad de suelo {profile.get('optimal_soil_moisture_min')} a {profile.get('optimal_soil_moisture_max')}%"
        )
        if profile.get("notes"):
            rag_query += f". características del cultivo: {profile.get('notes')}"
    if global_edaphology and global_edaphology.get("air_temp") is not None:
        rag_query += (
            f". contexto edafológico general: temperatura regional actual "
            f"{global_edaphology.get('air_temp'):.0f}°C"
        )

    action, priority = classify_action(rag_query, crop_name, sensor, profile)
    logger.info("RAG query generado: %s | acción: %s | prioridad: %s", rag_query, action, priority)

    # 2.1) Dedupe ligero: reutiliza fila sólo si el texto normalizado coincide con esta misma corrida (< 75 min).
    # Si cambia la telemetría, cambia típicamente juga_query → nueva recomendación aun teniendo mismas pendientes.
    if not req.force:
        rq_norm = rag_query.strip()
        with get_conn() as conn:
            dup = conn.execute(
                """
                SELECT id, user_crop_id, query_text, action, priority, detail_html, citations, status, faithfulness, created_at
                FROM recommendations
                WHERE user_crop_id = ?
                  AND action = ?
                  AND status = 'pendiente'
                ORDER BY id DESC
                LIMIT 1
                """,
                (req.user_crop_id, action),
            ).fetchone()
        if dup:
            dq_norm = str(dup[2] or "").strip()
            try:
                dup_created = datetime.fromisoformat(str(dup[9]).replace("Z", ""))
                age_seconds = (datetime.now() - dup_created).total_seconds()
            except Exception:
                age_seconds = 999999
            if dq_norm == rq_norm and age_seconds <= (75 * 60):
                cols = ["id", "user_crop_id", "query_text", "action", "priority", "detail_html", "citations", "status", "faithfulness", "created_at"]
                return _row_to_dict(dup, cols)

    # 3) Ejecutar consulta RAG
    detail_html = ""
    citations_json = "[]"
    faithfulness = 0.0

    try:
        from milpa_ai_backend.api.rag import get_retriever
        from milpa_ai_backend.core.logic.rag_engine import rerank_by_term_coverage, insufficient_evidence
        from milpa_ai_backend.core.logic.synthesis import compose_answer

        retriever = get_retriever()
        hits = retriever.hybrid(rag_query, final_k=16, labels_filter=None)

        # Cargar textos para reranking
        fragment_texts = {}
        with get_conn() as conn:
            cur = conn.cursor()
            for h in hits:
                fid = h["fragment_id"]
                cur.execute("SELECT text FROM fragments WHERE fragment_id = ?", (fid,))
                row = cur.fetchone()
                if row:
                    fragment_texts[fid] = row[0] or ""

        hits = rerank_by_term_coverage(rag_query, hits, fragment_texts)
        hits = hits[:8]

        is_insuf, diag, hits_filtered = insufficient_evidence(rag_query, hits)

        if not is_insuf and hits_filtered:
            # Preparar fragmentos para síntesis con autor/título
            frags_for_synth = []
            with get_conn() as conn:
                cur = conn.cursor()
                for h in hits_filtered:
                    fid = h["fragment_id"]
                    text = fragment_texts.get(fid, "")
                    cur.execute(
                        "SELECT f.doc_id, f.page_start, d.title, d.author "
                        "FROM fragments f LEFT JOIN docs d ON f.doc_id = d.doc_id "
                        "WHERE f.fragment_id = ?", (fid,)
                    )
                    meta_row = cur.fetchone()
                    doc_id = meta_row[0] if meta_row else "unknown"
                    page = meta_row[1] if meta_row else None
                    title = meta_row[2] if meta_row else None
                    author = meta_row[3] if meta_row else None

                    frags_for_synth.append({
                        "text": text,
                        "doc_id": doc_id,
                        "page_start": page,
                        "doc_title": title,
                        "doc_author": author,
                        "score": h.get("rrf_score", h.get("score", 0.0)),
                    })

            result = compose_answer(query=rag_query, fragments=frags_for_synth, max_length=600)
            detail_html = _sanitize_recommendation_detail(result.get("respuesta_html", ""), crop_name)
            citas = result.get("citas", [])
            citations_json = json.dumps(citas, ensure_ascii=False)
            faithfulness = result.get("faithfulness", 0.0)
        else:
            detail_html = _sanitize_recommendation_detail(_build_fallback_recommendation(crop_name, sensor, action), crop_name)

    except Exception as e:
        logger.warning("RAG pipeline falló, usando recomendación basada en reglas: %s", e)
        detail_html = _sanitize_recommendation_detail(_build_fallback_recommendation(crop_name, sensor, action), crop_name)

    # 4) Guardar recomendación
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recommendations (user_crop_id, query_text, action, priority, detail_html, citations, faithfulness) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (req.user_crop_id, rag_query, action, priority, detail_html, citations_json, faithfulness)
        )
        conn.commit()
        rec_id = cur.lastrowid
        cur2 = conn.execute(
            "SELECT id, user_crop_id, query_text, action, priority, detail_html, citations, status, faithfulness, created_at "
            "FROM recommendations WHERE id = ?", (rec_id,)
        )
        row = cur2.fetchone()

    cols = ["id", "user_crop_id", "query_text", "action", "priority", "detail_html", "citations", "status", "faithfulness", "created_at"]
    return _row_to_dict(row, cols)


# ───────── CALENDARIO AGRÍCOLA — PLAN RAG (con citas) ─────────
#
# La pantalla calendario.html debe poder generar "próximas actividades" usando
# evidencia real de la biblioteca (RAG), no reglas hardcodeadas.
#
# Lógica:
#   1. Para el cultivo seleccionado, calcular días desde siembra y etapa fenológica.
#   2. Para cada actividad esperable en las próximas 4 semanas (riego, fertilización,
#      control de plagas, monitoreo, cosecha si aplica), construir consultas RAG
#      enfocadas en la etapa actual.
#   3. Para cada consulta, tomar el mejor fragmento del retriever híbrido y devolverlo
#      como justificación clicable (doc_id + página).
#   4. Si no hay evidencia suficiente, el item queda marcado como `evidence: false`
#      pero igual se sugiere para que el usuario decida.
# ──────────────────────────────────────────────────────────────────────────────


_RAG_CALENDAR_PLAN_TEMPLATES = [
    {
        "stage_match": ("establecimiento", "vegetativo", "floración", "fructificación"),
        "event_type": "irrigation",
        "title_tpl": "Riego programado — {crop_display}",
        "day_offset": 4,
        "query_tpl": "calendario de riego del cultivo de {crop_name} en etapa {stage} "
                     "frecuencia litros volumen por evento humedad de suelo óptima",
    },
    {
        "stage_match": ("establecimiento", "vegetativo", "floración"),
        "event_type": "fertilization",
        "title_tpl": "Fertilización — {crop_display}",
        "day_offset": 10,
        "query_tpl": "fertilización del cultivo de {crop_name} en etapa {stage} "
                     "macronutrientes nitrógeno fósforo potasio dosis",
    },
    {
        "stage_match": ("vegetativo", "floración", "fructificación"),
        "event_type": "pest",
        "title_tpl": "Inspección de plagas — {crop_display}",
        "day_offset": 7,
        "query_tpl": "manejo integrado de plagas del cultivo de {crop_name} etapa {stage} "
                     "monitoreo umbrales control biológico",
    },
    {
        "stage_match": ("establecimiento", "vegetativo", "floración", "fructificación", "cosecha"),
        "event_type": "monitoring",
        "title_tpl": "Visita de campo — {crop_display}",
        "day_offset": 3,
        "query_tpl": "monitoreo agronómico semanal del cultivo de {crop_name} en etapa {stage} "
                     "humedad suelo malezas plagas fenología",
    },
    {
        "stage_match": ("fructificación", "cosecha"),
        "event_type": "harvest",
        "title_tpl": "Ventana de cosecha — {crop_display}",
        "day_offset": 14,
        "query_tpl": "ventana de cosecha del cultivo de {crop_name} indicadores de madurez "
                     "color firmeza grados brix tiempo desde floración",
    },
]


def _best_rag_fragment(query: str, k: int = 6) -> Optional[Dict[str, Any]]:
    """
    Llama al retriever híbrido y devuelve el mejor fragmento con metadata
    de documento (título, autor, página). Si no hay retriever disponible o
    no hay evidencia, devuelve None.
    """
    try:
        from milpa_ai_backend.api.rag import get_retriever
        from milpa_ai_backend.core.logic.rag_engine import rerank_by_term_coverage
        retriever = get_retriever()
        hits = retriever.hybrid(query, final_k=k, labels_filter=None)
        if not hits:
            return None
        with get_conn() as conn:
            cur = conn.cursor()
            texts: Dict[str, str] = {}
            for h in hits:
                fid = h.get("fragment_id")
                if not fid:
                    continue
                row = cur.execute("SELECT text FROM fragments WHERE fragment_id = ?", (fid,)).fetchone()
                if row:
                    texts[fid] = row[0] or ""
            hits = rerank_by_term_coverage(query, hits, texts)
            if not hits:
                return None
            top = hits[0]
            fid = top.get("fragment_id")
            text = texts.get(fid, "")
            meta_row = cur.execute(
                "SELECT f.doc_id, f.page_start, d.title, d.author "
                "FROM fragments f LEFT JOIN docs d ON f.doc_id = d.doc_id "
                "WHERE f.fragment_id = ?", (fid,)
            ).fetchone()
            doc_id = meta_row[0] if meta_row else None
            page = meta_row[1] if meta_row else None
            title = meta_row[2] if meta_row else None
            author = meta_row[3] if meta_row else None
        return {
            "fragment_id": fid,
            "text": text[:480],
            "doc_id": doc_id,
            "doc_title": title,
            "doc_author": author,
            "page_start": page,
            "score": float(top.get("rrf_score") or top.get("score") or 0.0),
        }
    except Exception as exc:
        logger.warning("RAG calendar fragment lookup failed: %s", exc)
        return None


@router.post("/api/calendar/rag-plan/{user_crop_id}")
def calendar_rag_plan(user_crop_id: int):
    """
    Genera próximas actividades para un cultivo del usuario apoyándose en el RAG.

    Fundamento: cada actividad sugerida cita el documento + página que la respalda.
    Si la biblioteca no contiene evidencia suficiente para una etapa, la actividad
    se marca con `evidence: false` y un mensaje explícito.
    """
    with get_conn() as conn:
        crop_row = conn.execute(
            "SELECT id, user_id, crop_name, display_name, planted_at, growth_stage, progress "
            "FROM user_crops WHERE id = ?", (user_crop_id,)
        ).fetchone()
        if not crop_row:
            raise HTTPException(404, "Cultivo no encontrado")
        crop = {
            "id": crop_row[0], "user_id": crop_row[1], "crop_name": crop_row[2],
            "display_name": crop_row[3] or (crop_row[2] or "Cultivo").capitalize(),
            "planted_at": crop_row[4], "growth_stage": crop_row[5], "progress": crop_row[6] or 0,
        }

    pheno = _phenological_stage(crop["crop_name"] or "", crop.get("planted_at"))

    today = datetime.now().date()
    if crop.get("planted_at"):
        try:
            planted_date = datetime.fromisoformat(str(crop["planted_at"])[:10]).date()
        except Exception:
            planted_date = today
    else:
        planted_date = today

    base_date = max(today, planted_date)

    activities: List[Dict[str, Any]] = []
    for tpl in _RAG_CALENDAR_PLAN_TEMPLATES:
        if pheno["stage"] not in tpl["stage_match"]:
            continue
        suggested_date = (base_date + timedelta_days(tpl["day_offset"])).isoformat()
        query = tpl["query_tpl"].format(
            crop_name=crop["crop_name"], stage=pheno["stage"]
        )
        evidence = _best_rag_fragment(query, k=6)
        title = tpl["title_tpl"].format(crop_display=crop["display_name"])
        rationale_html: str
        evidence_payload: Optional[Dict[str, Any]] = None
        has_evidence = bool(evidence and (evidence.get("text") or "").strip())
        if has_evidence:
            ev = evidence  # type: ignore[assignment]
            cite = []
            if ev.get("doc_title"):
                cite.append(ev["doc_title"])
            if ev.get("page_start") is not None:
                cite.append(f"p. {ev['page_start']}")
            cite_line = " — " + ", ".join(cite) if cite else ""
            rationale_html = (
                f"<p>{ev['text']}</p>"
                f"<p class='small text-muted mb-0'>Fuente RAG{cite_line}</p>"
            )
            evidence_payload = {
                "doc_id": ev.get("doc_id"),
                "doc_title": ev.get("doc_title"),
                "doc_author": ev.get("doc_author"),
                "page_start": ev.get("page_start"),
                "score": ev.get("score"),
                "fragment_text": ev.get("text"),
            }
        else:
            rationale_html = (
                "<p class='text-muted small mb-0'>"
                "Sin evidencia suficiente en la biblioteca para esta etapa. "
                "La actividad queda como sugerencia operativa basada en la fenología."
                "</p>"
            )

        activities.append({
            "user_crop_id": crop["id"],
            "title": title,
            "event_type": tpl["event_type"],
            "stage": pheno["stage"],
            "suggested_date": suggested_date,
            "rationale_html": rationale_html,
            "rag_query": query,
            "evidence": has_evidence,
            "source": evidence_payload,
        })

    return {
        "user_crop_id": crop["id"],
        "crop_name": crop["crop_name"],
        "display_name": crop["display_name"],
        "planted_at": crop["planted_at"],
        "phenology": pheno,
        "horizon_days": max(t["day_offset"] for t in _RAG_CALENDAR_PLAN_TEMPLATES),
        "activities": activities,
        "basis": "Cada actividad cita el documento y página de la biblioteca MILPA "
                 "que la respalda; si no hay evidencia suficiente, se etiqueta como tal.",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def timedelta_days(n: int):
    """Helper local: timedelta(days=n) sin imports adicionales."""
    from datetime import timedelta
    return timedelta(days=int(n))


def _build_fallback_recommendation(crop_name: str, sensor: dict, action: str) -> str:
    """Genera una recomendación basada en reglas cuando el RAG no tiene información suficiente."""
    sm = sensor.get("soil_moisture", 50)
    temp = sensor.get("air_temp", 25)
    hum = sensor.get("air_humidity", 50)

    lines = [f"<h5>Recomendación para {crop_name}</h5>"]
    lines.append(f"<p><strong>Acción sugerida:</strong> {action}</p>")
    lines.append("<ul>")

    if sm < 30:
        lines.append(f"<li>La humedad del suelo está en {sm:.0f}%. Se recomienda riego inmediato, preferiblemente por goteo para optimizar el uso del agua.</li>")
    elif sm > 80:
        lines.append(f"<li>La humedad del suelo está en {sm:.0f}%. Verificar drenaje y evitar encharcamiento que puede causar pudrición de raíces.</li>")
    else:
        lines.append(f"<li>Humedad del suelo en {sm:.0f}% — nivel adecuado. Mantener monitoreo.</li>")

    if temp > 35:
        lines.append(f"<li>Temperatura de {temp:.0f}°C. Aplicar acolchado (mulch) para proteger raíces y considerar malla sombra.</li>")
    elif temp < 10:
        lines.append(f"<li>Temperatura de {temp:.0f}°C. Riesgo de helada: proteger con cobertura plástica o agrotextil.</li>")

    if hum < 30:
        lines.append(f"<li>Humedad ambiental baja ({hum:.0f}%). Considerar riego foliar temprano por la mañana.</li>")
    elif hum > 85:
        lines.append(f"<li>Humedad ambiental alta ({hum:.0f}%). Monitorear signos de enfermedades fúngicas (roya, cenicilla, antracnosis).</li>")

    lines.append("</ul>")
    lines.append("<p><em>Nota: Esta recomendación se basa en reglas generales. Consulte fuentes especializadas para su región y variedad específica.</em></p>")
    return "\n".join(lines)


# ───────── Soil Nutrients (análisis N/P/K por cultivo) ─────────

class SoilNutrientCreate(BaseModel):
    user_crop_id: int
    nitrogen: Optional[float] = None
    phosphorus: Optional[float] = None
    potassium: Optional[float] = None
    nitrogen_opt_min: Optional[float] = 3.0
    nitrogen_opt_max: Optional[float] = 4.0
    phosphorus_opt_min: Optional[float] = 2.0
    phosphorus_opt_max: Optional[float] = 3.0
    potassium_opt_min: Optional[float] = 2.5
    potassium_opt_max: Optional[float] = 3.5
    notes: Optional[str] = None


@router.get("/api/soil-nutrients/{user_crop_id}/latest")
def get_soil_nutrients_latest(user_crop_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM soil_nutrients WHERE user_crop_id=? ORDER BY created_at DESC LIMIT 1",
            (user_crop_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No hay análisis de nutrientes para este cultivo")
    cols = ["id","user_crop_id","nitrogen","phosphorus","potassium",
            "nitrogen_opt_min","nitrogen_opt_max","phosphorus_opt_min",
            "phosphorus_opt_max","potassium_opt_min","potassium_opt_max","notes","created_at"]
    return dict(zip(cols, row))


@router.get("/api/soil-nutrients/{user_crop_id}")
def get_soil_nutrients(user_crop_id: int, limit: int = 12):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM soil_nutrients WHERE user_crop_id=? ORDER BY created_at DESC LIMIT ?",
            (user_crop_id, limit)
        ).fetchall()
    cols = ["id","user_crop_id","nitrogen","phosphorus","potassium",
            "nitrogen_opt_min","nitrogen_opt_max","phosphorus_opt_min",
            "phosphorus_opt_max","potassium_opt_min","potassium_opt_max","notes","created_at"]
    return [dict(zip(cols, r)) for r in rows]


@router.post("/api/soil-nutrients")
def create_soil_nutrients(body: SoilNutrientCreate):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO soil_nutrients
               (user_crop_id, nitrogen, phosphorus, potassium,
                nitrogen_opt_min, nitrogen_opt_max, phosphorus_opt_min,
                phosphorus_opt_max, potassium_opt_min, potassium_opt_max, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (body.user_crop_id, body.nitrogen, body.phosphorus, body.potassium,
             body.nitrogen_opt_min, body.nitrogen_opt_max,
             body.phosphorus_opt_min, body.phosphorus_opt_max,
             body.potassium_opt_min, body.potassium_opt_max, body.notes)
        )
        conn.commit()
        new_id = cur.lastrowid
    return {"id": new_id, "user_crop_id": body.user_crop_id}


# ───────── Irrigation Events (riego por cultivo con datos reales) ─────────

class IrrigationEventCreate(BaseModel):
    user_crop_id: int
    event_date: str                            # 'YYYY-MM-DD'
    liters_applied: float
    duration_minutes: Optional[int] = None
    method: Optional[str] = "goteo"            # goteo | aspersion | manual | surcos
    soil_moisture_before: Optional[float] = None
    soil_moisture_after: Optional[float] = None
    notes: Optional[str] = None


_IRRIG_COLS = [
    "id", "user_crop_id", "event_date", "liters_applied", "duration_minutes",
    "method", "soil_moisture_before", "soil_moisture_after", "notes", "created_at"
]


@router.get("/api/irrigation-events/{user_crop_id}")
def list_irrigation_events(user_crop_id: int, limit: int = 30):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM irrigation_events WHERE user_crop_id=? ORDER BY event_date DESC LIMIT ?",
            (user_crop_id, limit)
        ).fetchall()
    return [dict(zip(_IRRIG_COLS, r)) for r in rows]


@router.get("/api/irrigation-events/{user_crop_id}/efficiency")
def get_irrigation_efficiency(user_crop_id: int):
    """Calcula métricas reales de eficiencia de riego desde irrigation_events.

    Los óptimos por cultivo (litros, frecuencia, duración, delta esperado) y los
    valores objetivo del radar se leen desde `crop_profiles` (migración 0010).
    Si el cultivo no tiene perfil, usa valores conservadores genéricos.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM irrigation_events WHERE user_crop_id=? ORDER BY event_date DESC LIMIT 30",
            (user_crop_id,)
        ).fetchall()
        crop_row = conn.execute(
            "SELECT crop_name FROM user_crops WHERE id=?", (user_crop_id,)
        ).fetchone()
        crop_name = (crop_row[0] if crop_row else "maiz")
        prof = conn.execute(
            """SELECT optimal_irrigation_liters, optimal_irrigation_freq_per_month,
                      optimal_irrigation_duration_min, expected_irrigation_delta_pct,
                      optimal_radar_json
               FROM crop_profiles WHERE crop_name=? LIMIT 1""",
            (crop_name,)
        ).fetchone()
    if not rows:
        raise HTTPException(status_code=404, detail="No hay eventos de riego registrados para este cultivo")

    OPTIMAL_LITERS = float(prof[0]) if prof and prof[0] else 45.0
    OPTIMAL_FREQ = float(prof[1]) if prof and prof[1] else 4.0
    OPTIMAL_DUR = float(prof[2]) if prof and prof[2] else 35.0
    EXPECTED_DELTA = float(prof[3]) if prof and prof[3] else 12.0
    try:
        optimal_radar = json.loads(prof[4]) if prof and prof[4] else [90, 85, 95, 90, 95]
        if not (isinstance(optimal_radar, list) and len(optimal_radar) == 5):
            optimal_radar = [90, 85, 95, 90, 95]
    except Exception:
        optimal_radar = [90, 85, 95, 90, 95]

    events = [dict(zip(_IRRIG_COLS, r)) for r in rows]

    avg_liters = sum(e["liters_applied"] for e in events) / len(events)
    cantidad = round(min(100, (avg_liters / OPTIMAL_LITERS) * 100))

    from datetime import datetime as dt, timedelta
    cutoff = (dt.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [e for e in events if e["event_date"] >= cutoff]
    frecuencia = round(min(100, (len(recent) / OPTIMAL_FREQ) * 100))

    absorciones = []
    for e in events:
        if e["soil_moisture_before"] is not None and e["soil_moisture_after"] is not None and e["liters_applied"] > 0:
            delta = e["soil_moisture_after"] - e["soil_moisture_before"]
            absorciones.append(min(100, max(0, (delta / EXPECTED_DELTA) * 100)))
    absorcion = round(sum(absorciones) / len(absorciones)) if absorciones else 70

    afters = [e["soil_moisture_after"] for e in events if e["soil_moisture_after"] is not None]
    if afters:
        mean_after = sum(afters) / len(afters)
        variance = sum((x - mean_after) ** 2 for x in afters) / len(afters)
        distribucion = round(max(40, 100 - variance * 2))
    else:
        distribucion = 70

    durations = [e["duration_minutes"] for e in events if e["duration_minutes"] is not None]
    if durations:
        avg_dur = sum(durations) / len(durations)
        tiempo = round(min(100, (avg_dur / OPTIMAL_DUR) * 100))
    else:
        tiempo = 75

    eficiencia_actual = round((cantidad + frecuencia + distribucion + absorcion + tiempo) / 5)
    mejora_posible = max(0, 91 - eficiencia_actual)

    return {
        "user_crop_id": user_crop_id,
        "crop_name": crop_name,
        "event_count": len(events),
        "avg_liters_per_event": round(avg_liters, 1),
        "recent_events_30d": len(recent),
        "metrics": {
            "cantidad": cantidad,
            "frecuencia": frecuencia,
            "distribucion": distribucion,
            "absorcion": absorcion,
            "tiempo": tiempo,
        },
        "eficiencia_actual": eficiencia_actual,
        "mejora_posible": mejora_posible,
        "optimal_values": optimal_radar,
        "optimal_targets": {
            "liters_per_event": OPTIMAL_LITERS,
            "freq_per_month": OPTIMAL_FREQ,
            "duration_min": OPTIMAL_DUR,
            "expected_delta_pct": EXPECTED_DELTA,
        },
        "last_event": events[0] if events else None,
    }


@router.post("/api/irrigation-events", status_code=201)
def create_irrigation_event(body: IrrigationEventCreate):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO irrigation_events
               (user_crop_id, event_date, liters_applied, duration_minutes, method,
                soil_moisture_before, soil_moisture_after, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (body.user_crop_id, body.event_date, body.liters_applied, body.duration_minutes,
             body.method, body.soil_moisture_before, body.soil_moisture_after, body.notes)
        )
        conn.commit()
        new_id = cur.lastrowid
    return {"id": new_id, "user_crop_id": body.user_crop_id}


# ───────── Admin: listado de usuarios (sin auth — uso interno del presenter) ─────────

@router.get("/admin/users")
def list_admin_users():
    """Retorna usuarios con conteo de cultivos y lecturas de sensores.
    Endpoint interno — solo accesible desde localhost (presenter admin)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                u.id,
                u.username,
                COUNT(DISTINCT c.id) AS crop_count,
                COUNT(sr.id) AS sensor_readings_count,
                MAX(sr.created_at) AS last_sensor_at
            FROM users u
            LEFT JOIN user_crops c ON c.user_id = u.id
            LEFT JOIN sensor_readings sr ON sr.user_crop_id = c.id
            GROUP BY u.id, u.username
            ORDER BY u.username ASC
        """).fetchall()
    col_names = ["id", "username", "crop_count", "sensor_readings_count", "last_sensor_at"]
    return [dict(zip(col_names, row)) for row in rows]
