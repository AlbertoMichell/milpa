"""
Genera datos sintéticos realistas de sensores para los cultivos existentes.
Crea lecturas cada ~6 horas durante los últimos 14 días + recomendaciones.
"""
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parent / "data" / "milpa_knowledge.db")

# Perfiles por cultivo: rangos típicos de valores de sensores
PROFILES = {
    "maiz": {
        "soil_moisture": (45, 75), "air_temp": (18, 34), "air_humidity": (40, 70),
        "light": (60, 95), "precipitation": (0, 15), "wind_speed": (0, 20),
    },
    "frijol": {
        "soil_moisture": (40, 70), "air_temp": (16, 30), "air_humidity": (45, 75),
        "light": (55, 90), "precipitation": (0, 12), "wind_speed": (0, 18),
    },
    "calabaza": {
        "soil_moisture": (50, 80), "air_temp": (20, 35), "air_humidity": (50, 80),
        "light": (65, 95), "precipitation": (0, 10), "wind_speed": (0, 15),
    },
    "chile": {
        "soil_moisture": (35, 65), "air_temp": (20, 38), "air_humidity": (30, 60),
        "light": (70, 98), "precipitation": (0, 8), "wind_speed": (0, 22),
    },
    "tomate": {
        "soil_moisture": (45, 70), "air_temp": (18, 32), "air_humidity": (50, 75),
        "light": (60, 92), "precipitation": (0, 10), "wind_speed": (0, 16),
    },
}


def _rand(lo, hi, prev=None, jitter=0.15):
    """Genera valor con tendencia suave (random walk acotado)."""
    if prev is not None:
        delta = (hi - lo) * jitter * random.uniform(-1, 1)
        val = prev + delta
    else:
        val = random.uniform(lo, hi)
    return round(max(lo, min(hi, val)), 1)


def generate():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # Obtener cultivos
    cur.execute("SELECT id, crop_name FROM user_crops")
    crops = cur.fetchall()
    if not crops:
        print("No hay cultivos. Nada que hacer.")
        return

    now = datetime(2026, 4, 17, 22, 0, 0)
    days_back = 14
    interval_hours = 6
    readings_per_crop = (days_back * 24) // interval_hours  # 56 lecturas

    total_inserted = 0

    for crop_id, crop_name in crops:
        profile = PROFILES.get(crop_name, PROFILES["maiz"])

        # Borrar lecturas de seed (la única existente) para evitar duplicados
        cur.execute("DELETE FROM sensor_readings WHERE user_crop_id = ?", (crop_id,))

        prev = {}  # estado anterior para random walk
        for i in range(readings_per_crop):
            ts = now - timedelta(hours=(readings_per_crop - i) * interval_hours)
            # Variación diurna: temp sube de día, baja de noche
            hour = ts.hour
            temp_offset = 4 * (1 if 10 <= hour <= 16 else -1 if hour < 6 or hour > 20 else 0)

            sm = _rand(*profile["soil_moisture"], prev.get("sm"))
            at = _rand(profile["air_temp"][0] + temp_offset,
                       profile["air_temp"][1] + temp_offset, prev.get("at"))
            ah = _rand(*profile["air_humidity"], prev.get("ah"))
            lt = _rand(*profile["light"], prev.get("lt"))
            # Precipitación: 70% de las veces es 0
            pr = 0.0 if random.random() < 0.7 else round(random.uniform(0.5, profile["precipitation"][1]), 1)
            ws = _rand(*profile["wind_speed"], prev.get("ws"))

            # Eventos extremos ocasionales (~5% de lecturas)
            if random.random() < 0.05:
                event = random.choice(["drought", "heat", "rain"])
                if event == "drought":
                    sm = round(random.uniform(8, 20), 1)
                elif event == "heat":
                    at = round(random.uniform(36, 42), 1)
                elif event == "rain":
                    pr = round(random.uniform(20, 45), 1)
                    sm = min(95, sm + 20)

            prev = {"sm": sm, "at": at, "ah": ah, "lt": lt, "ws": ws}

            cur.execute(
                "INSERT INTO sensor_readings "
                "(user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (crop_id, sm, at, ah, lt, pr, ws, ts.strftime("%Y-%m-%d %H:%M:%S"))
            )
            total_inserted += 1

    conn.commit()
    print(f"✅ Insertadas {total_inserted} lecturas de sensores para {len(crops)} cultivos ({readings_per_crop} lecturas/cultivo)")

    # Verificar
    cur.execute("SELECT user_crop_id, COUNT(*), MIN(created_at), MAX(created_at) FROM sensor_readings GROUP BY user_crop_id")
    for row in cur.fetchall():
        cur2 = conn.execute("SELECT crop_name FROM user_crops WHERE id = ?", (row[0],))
        name = cur2.fetchone()[0]
        print(f"  {name}: {row[1]} lecturas [{row[2]} → {row[3]}]")

    conn.close()


if __name__ == "__main__":
    generate()
