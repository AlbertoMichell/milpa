#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


CORE_TABLES = [
    "users", "user_crops", "sensor_readings", "edaphology_global_readings",
    "crop_profiles", "recommendations", "soil_nutrients", "irrigation_events",
    "documents", "chunks", "chat_messages",
]


def rows_to_dicts(cur: sqlite3.Cursor, rows: List[tuple]) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description or []]
    return [dict(zip(cols, row)) for row in rows]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def sample(conn: sqlite3.Connection, table: str, limit: int = 5) -> List[Dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    order = ""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if "created_at" in cols:
        order = " ORDER BY datetime(created_at) DESC"
    elif "id" in cols:
        order = " ORDER BY id DESC"
    cur = conn.execute(f"SELECT * FROM {table}{order} LIMIT ?", (limit,))
    return rows_to_dicts(cur, cur.fetchall())


def latest_sensor_summary(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not table_exists(conn, "user_crops") or not table_exists(conn, "sensor_readings"):
        return []
    sql = """
    SELECT c.user_id, c.id AS user_crop_id, c.crop_name, c.display_name, c.status,
           sr.soil_moisture, sr.air_temp, sr.air_humidity, sr.light,
           sr.precipitation, sr.wind_speed, sr.created_at AS reading_at
    FROM user_crops c
    LEFT JOIN sensor_readings sr ON sr.id = (
        SELECT s2.id FROM sensor_readings s2
        WHERE s2.user_crop_id = c.id
        ORDER BY datetime(s2.created_at) DESC, s2.id DESC LIMIT 1
    )
    ORDER BY c.user_id, c.id
    """
    cur = conn.execute(sql)
    return rows_to_dicts(cur, cur.fetchall())


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecciona la BD operacional de MILPA para validar AgroBot.")
    parser.add_argument("db", nargs="?", default="milpa_ai_backend/data/milpa_knowledge.db")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la BD: {db_path}")
        print("Recuerda que el repo ignora milpa_ai_backend/data/*.db; debes correr esto en tu máquina local.")
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report: Dict[str, Any] = {"db_path": str(db_path), "tables": {}, "latest_sensors": []}
    for table in CORE_TABLES:
        report["tables"][table] = {
            "exists": table_exists(conn, table),
            "count": count(conn, table),
            "sample": sample(conn, table, limit=3),
        }
    report["latest_sensors"] = latest_sensor_summary(conn)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"BD: {db_path}")
        for table, info in report["tables"].items():
            state = "OK" if info["exists"] else "NO EXISTE"
            print(f"- {table}: {state}, filas={info['count']}")
        print("\nÚltimas lecturas por cultivo:")
        for row in report["latest_sensors"]:
            print(
                f"  user={row.get('user_id')} crop={row.get('crop_name')} "
                f"soil={row.get('soil_moisture')} temp={row.get('air_temp')} "
                f"HR={row.get('air_humidity')} wind={row.get('wind_speed')} at={row.get('reading_at')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
