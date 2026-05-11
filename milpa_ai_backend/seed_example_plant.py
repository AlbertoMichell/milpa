"""Carga una planta de ejemplo y dataset mínimo si faltan registros."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parent / "data" / "milpa_knowledge.db")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Usuario base
    cur.execute("SELECT id FROM users WHERE username = ?", ("testuser",))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        cur.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, datetime('now'))",
            ("testuser", "$2a$10$abcdefghijklmnopqrstuv"),
        )
        user_id = cur.lastrowid

    # Planta ejemplo: chile serrano
    cur.execute(
        "SELECT id FROM user_crops WHERE user_id = ? AND crop_name = ?",
        (user_id, "chile"),
    )
    crop = cur.fetchone()
    if crop:
        crop_id = crop[0]
    else:
        cur.execute(
            "INSERT INTO user_crops (user_id, crop_name, variety, planted_at, status, progress, notes) "
            "VALUES (?, ?, ?, ?, 'activo', ?, ?)",
            (user_id, "chile", "Serrano", "2026-03-15", 35, "Planta ejemplo para validación RAG")
        )
        crop_id = cur.lastrowid

    # Dataset base: si no hay lecturas, crear serie simple de 7 días
    cur.execute("SELECT COUNT(*) FROM sensor_readings WHERE user_crop_id = ?", (crop_id,))
    count = cur.fetchone()[0]
    if count == 0:
        now = datetime(2026, 4, 20, 12, 0, 0)
        for i in range(28):
            ts = now - timedelta(hours=(27 - i) * 6)
            cur.execute(
                "INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    crop_id,
                    48.0 + (i % 5) * 1.2,
                    27.0 + (i % 4) * 0.7,
                    50.0 + (i % 3) * 1.5,
                    72.0 + (i % 4) * 2.0,
                    0.0 if i % 6 else 3.0,
                    7.0 + (i % 3),
                    ts.strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

    conn.commit()
    conn.close()
    print("OK: planta ejemplo y dataset verificados")


if __name__ == "__main__":
    main()
