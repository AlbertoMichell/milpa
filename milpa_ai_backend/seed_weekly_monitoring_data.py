"""Seed historical weekly monitoring data into the unified SQLite database.

This script inserts one reading per week for each user crop and one global
edaphology record per week. It is idempotent by (crop, date) and (global date).
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "milpa_knowledge.db"
WEEKS = 24

CROP_PROFILES = {
    "maiz": {"soil": (44.0, 72.0), "temp": (18.0, 34.0), "humidity": (40.0, 72.0), "light": (58.0, 90.0)},
    "frijol": {"soil": (40.0, 68.0), "temp": (16.0, 31.0), "humidity": (46.0, 78.0), "light": (50.0, 82.0)},
    "calabaza": {"soil": (48.0, 80.0), "temp": (20.0, 35.0), "humidity": (50.0, 82.0), "light": (52.0, 84.0)},
    "chile": {"soil": (34.0, 64.0), "temp": (20.0, 36.0), "humidity": (35.0, 68.0), "light": (62.0, 92.0)},
    "tomate": {"soil": (44.0, 72.0), "temp": (18.0, 32.0), "humidity": (50.0, 76.0), "light": (56.0, 88.0)},
    "default": {"soil": (40.0, 70.0), "temp": (18.0, 33.0), "humidity": (45.0, 75.0), "light": (55.0, 88.0)},
}


def bounded_wave(low: float, high: float, idx: int, phase: float) -> float:
    mid = (low + high) / 2.0
    amp = (high - low) / 2.0
    value = mid + amp * math.sin((idx / 3.0) + phase)
    return round(max(low, min(high, value)), 1)


def reading_exists_for_day(cur: sqlite3.Cursor, crop_id: int, day_iso: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sensor_readings WHERE user_crop_id = ? AND date(created_at) = ? LIMIT 1",
        (crop_id, day_iso),
    ).fetchone()
    return row is not None


def global_exists_for_day(cur: sqlite3.Cursor, day_iso: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM edaphology_global_readings WHERE date(created_at) = ? LIMIT 1",
        (day_iso,),
    ).fetchone()
    return row is not None


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database file not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    crops = cur.execute(
        "SELECT id, crop_name FROM user_crops WHERE status = 'activo' ORDER BY id ASC"
    ).fetchall()

    if not crops:
        print("No active crops found. Nothing to seed.")
        conn.close()
        return

    anchor = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    crop_inserts = 0
    global_inserts = 0

    for crop_id, crop_name in crops:
        profile = CROP_PROFILES.get((crop_name or "").lower(), CROP_PROFILES["default"])
        phase = (crop_id % 7) * 0.31

        for week in range(WEEKS):
            ts = anchor - timedelta(days=(WEEKS - 1 - week) * 7)
            day_iso = ts.strftime("%Y-%m-%d")
            ts_iso = ts.strftime("%Y-%m-%d %H:%M:%S")

            if not reading_exists_for_day(cur, crop_id, day_iso):
                soil = bounded_wave(profile["soil"][0], profile["soil"][1], week, phase)
                temp = bounded_wave(profile["temp"][0], profile["temp"][1], week, phase + 0.5)
                humidity = bounded_wave(profile["humidity"][0], profile["humidity"][1], week, phase + 1.0)
                light = bounded_wave(profile["light"][0], profile["light"][1], week, phase + 1.5)
                precipitation = round(max(0.0, 6.5 * math.sin((week / 2.7) + phase)), 1)
                wind_speed = round(6.0 + 3.0 * abs(math.sin((week / 2.1) + phase)), 1)

                cur.execute(
                    "INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (crop_id, soil, temp, humidity, light, precipitation, wind_speed, ts_iso),
                )
                crop_inserts += 1

            if not global_exists_for_day(cur, day_iso):
                soil_temp = bounded_wave(18.0, 28.0, week, 0.8)
                air_temp = bounded_wave(16.0, 36.0, week, 0.4)
                air_humidity = bounded_wave(38.0, 82.0, week, 1.2)
                soil_moisture = bounded_wave(32.0, 76.0, week, 1.7)
                precipitation = round(max(0.0, 8.0 * math.sin((week / 2.5) + 0.9)), 1)
                wind_speed = round(5.5 + 3.2 * abs(math.sin((week / 2.2) + 1.1)), 1)
                ph = bounded_wave(5.9, 7.1, week, 0.2)
                conductivity = bounded_wave(0.8, 1.6, week, 0.6)

                cur.execute(
                    "INSERT INTO edaphology_global_readings "
                    "(location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "general",
                        soil_temp,
                        air_temp,
                        air_humidity,
                        soil_moisture,
                        precipitation,
                        wind_speed,
                        ph,
                        conductivity,
                        "Serie semanal historica para monitoreo.",
                        ts_iso,
                    ),
                )
                global_inserts += 1

    conn.commit()

    per_crop_stats = cur.execute(
        "SELECT c.crop_name, COUNT(sr.id), MIN(sr.created_at), MAX(sr.created_at) "
        "FROM user_crops c "
        "LEFT JOIN sensor_readings sr ON sr.user_crop_id = c.id "
        "GROUP BY c.id "
        "ORDER BY c.id"
    ).fetchall()

    print(f"DB: {DB_PATH}")
    print(f"Active crops: {len(crops)}")
    print(f"Inserted crop weekly readings: {crop_inserts}")
    print(f"Inserted global weekly readings: {global_inserts}")
    for crop_name, total, min_ts, max_ts in per_crop_stats:
        print(f"- {crop_name}: {total} readings ({min_ts} -> {max_ts})")

    conn.close()


if __name__ == "__main__":
    main()
