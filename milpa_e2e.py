"""
milpa_e2e.py — Pipeline reproducible end-to-end del sistema MILPA.

Ejecuta, en este orden, todo lo necesario para validar que el sistema
funciona "al 100 por ciento" desde el punto de vista del backend:

  1. Aplica las migraciones SQL pendientes (yoyo).
  2. Crea (o actualiza) un usuario demo "milpa_demo" con perfil + settings.
  3. Crea (o reutiliza) un cultivo de maíz para ese usuario.
  4. Inyecta una lectura de sensor de "estrés térmico" (37 °C, 22 % HS, 28 % HA).
  5. Sube y reindexa el libro agronómico docs/manual_maiz_milpa_2026.txt
     en la biblioteca RAG (BM25 + ChromaDB) usando /api/documents/ingest.
  6. Llama /api/recommendations/generate para el cultivo de maíz.
  7. Persiste y verifica la recomendación en la tabla `recommendations`.
  8. Imprime un checklist visual con cada paso aprobado / fallido.

Requisitos:
  - El backend FastAPI debe estar corriendo en http://127.0.0.1:8000
    (o exportar MILPA_BACKEND con la URL).
  - Si el backend no responde, el script ejecuta de todas formas las
    partes locales (migración, seeds, llamada al pipeline en proceso).

Uso:
    py milpa_e2e.py            # ejecuta el pipeline completo
    py milpa_e2e.py --no-http  # forzar modo "in-process" sin backend HTTP
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "milpa_ai_backend" / "data" / "milpa_knowledge.db"
BOOK_PATH = ROOT / "docs" / "manual_maiz_milpa_2026.txt"
BACKEND = os.environ.get("MILPA_BACKEND", "http://127.0.0.1:8000")

CHECKS: List[Dict[str, Any]] = []


def log(step: str, ok: bool, detail: str = ""):
    flag = "[ OK ]" if ok else "[FAIL]"
    print(f"{flag}  {step}\n        {detail}".rstrip())
    CHECKS.append({"step": step, "ok": ok, "detail": detail})


def http_get(path: str, timeout: int = 60) -> Optional[Any]:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"_error": str(exc)}


def http_post(path: str, payload: Dict[str, Any], timeout: int = 60) -> Optional[Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        try:
            return {"_error": exc.read().decode("utf-8"), "_status": exc.code}
        except Exception:
            return {"_error": str(exc), "_status": exc.code}
    except Exception as exc:
        return {"_error": str(exc)}


def http_post_multipart(path: str, file_path: Path, fields: Dict[str, str], timeout: int = 300) -> Optional[Any]:
    """Multipart upload sin dependencias externas (usa stdlib)."""
    boundary = f"----milpa{int(time.time()*1000)}"
    parts: List[bytes] = []
    for key, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file_path.name}\"\r\nContent-Type: text/plain\r\n\r\n".encode("utf-8")
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        try:
            return {"_error": exc.read().decode("utf-8"), "_status": exc.code}
        except Exception:
            return {"_error": str(exc), "_status": exc.code}
    except Exception as exc:
        return {"_error": str(exc)}


# ---------------------------------------------------------------------------
# 1. Migraciones (yoyo)
# ---------------------------------------------------------------------------

def run_migrations() -> bool:
    try:
        from yoyo import read_migrations, get_backend  # type: ignore
        backend = get_backend(f"sqlite:///{DB_PATH}")
        migrations = read_migrations(str(ROOT / "milpa_ai_backend" / "core" / "logic" / "migrations"))
        with backend.lock():
            applied = backend.apply_migrations(backend.to_apply(migrations))
        log("Migraciones SQL aplicadas (yoyo)", True, f"backend={backend!r}")
        return True
    except Exception as exc:
        log("Migraciones SQL aplicadas (yoyo)", False, f"error: {exc}")
        return False


# ---------------------------------------------------------------------------
# 2. Usuario + perfil + settings
# ---------------------------------------------------------------------------

def ensure_demo_user(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", ("milpa_demo",))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        # Hash bcrypt-compat para password "Milpa2026!" (usamos el algoritmo
        # del módulo bcrypt si está disponible, si no un placeholder seguro).
        try:
            import bcrypt  # type: ignore
            pwd_hash = bcrypt.hashpw(b"Milpa2026!", bcrypt.gensalt(10)).decode()
        except Exception:
            pwd_hash = "$2b$10$QbBdH0R0rL8wPVtYn4yCCOXX5mO6p1q8jKZqgC3oF0K8Y0A2fO0pe"
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("milpa_demo", pwd_hash),
        )
        user_id = cur.lastrowid

    cur.execute(
        """INSERT OR IGNORE INTO user_profiles (user_id, first_name, last_name, bio, location, experience, email, phone, language, lat, lon, geo_zoom)
           VALUES (?, 'Demo', 'Milpa', 'Productor sintético del E2E MILPA', 'Coatepec, Veracruz', '5-15 años', 'demo@milpa.local', '+52 228 0000000', 'Español', 19.4517, -96.9612, 14)""",
        (user_id,),
    )
    cur.execute(
        """UPDATE user_profiles SET lat = COALESCE(lat, 19.4517), lon = COALESCE(lon, -96.9612), geo_zoom = COALESCE(geo_zoom, 14)
           WHERE user_id = ?""",
        (user_id,),
    )
    cur.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
    conn.commit()
    return user_id


def ensure_demo_crop(conn: sqlite3.Connection, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM user_crops WHERE user_id = ? AND crop_name = 'maiz' ORDER BY id LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if row:
        crop_id = row[0]
        cur.execute(
            """UPDATE user_crops
               SET display_name = COALESCE(display_name, 'Maíz E2E MILPA'),
                   variety = COALESCE(variety, 'Criollo'),
                   status = 'activo',
                   progress = 65,
                   growth_stage = 'floracion',
                   sensor_x_pct = COALESCE(sensor_x_pct, 0.30),
                   sensor_y_pct = COALESCE(sensor_y_pct, 0.30),
                   image_path = COALESCE(image_path, 'elementos/maiz.jpg')
               WHERE id = ?""",
            (crop_id,),
        )
    else:
        cur.execute(
            """INSERT INTO user_crops
               (user_id, crop_name, display_name, variety, planted_at, expected_harvest_at, status, progress, growth_stage, sensor_x_pct, sensor_y_pct, image_path)
               VALUES (?, 'maiz', 'Maíz E2E MILPA', 'Criollo', date('now', '-70 days'), date('now', '+50 days'), 'activo', 65, 'floracion', 0.30, 0.30, 'elementos/maiz.jpg')""",
            (user_id,),
        )
        crop_id = cur.lastrowid
    conn.commit()
    return crop_id


def inject_stress_reading(conn: sqlite3.Connection, crop_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sensor_readings (user_crop_id, soil_moisture, air_temp, air_humidity, light, precipitation, wind_speed)
           VALUES (?, 22.0, 37.0, 28.0, 92.0, 0.0, 6.0)""",
        (crop_id,),
    )
    cur.execute(
        """INSERT INTO edaphology_global_readings
           (location_name, soil_temp, air_temp, air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes)
           VALUES ('coatepec', 30.0, 37.0, 28.0, 24.0, 0.0, 6.0, 6.4, 1.1, 'E2E: estrés térmico programado')""",
    )
    cur.execute(
        "SELECT COUNT(*) FROM irrigation_events WHERE user_crop_id = ?", (crop_id,)
    )
    if cur.fetchone()[0] == 0:
        for offset_days, liters, dur, sm_before, sm_after in [
            (-21, 30.0, 25, 28.0, 38.0),
            (-14, 35.0, 30, 30.0, 41.0),
            (-7,  40.0, 32, 26.0, 39.0),
            (-1,  22.0, 22, 22.0, 31.0),
        ]:
            cur.execute(
                f"""INSERT INTO irrigation_events
                    (user_crop_id, event_date, liters_applied, duration_minutes, method,
                     soil_moisture_before, soil_moisture_after, notes)
                    VALUES (?, date('now', '{offset_days} days'), ?, ?, 'goteo', ?, ?, 'E2E demo')""",
                (crop_id, liters, dur, sm_before, sm_after),
            )
    conn.commit()


def seed_demo(conn: sqlite3.Connection) -> Dict[str, Any]:
    user_id = ensure_demo_user(conn)
    crop_id = ensure_demo_crop(conn, user_id)
    inject_stress_reading(conn, crop_id)
    return {"user_id": user_id, "crop_id": crop_id}


# ---------------------------------------------------------------------------
# 3. Ingesta del libro
# ---------------------------------------------------------------------------

def ingest_book(use_http: bool) -> Dict[str, Any]:
    if not BOOK_PATH.exists():
        log("Libro agronómico encontrado", False, f"no existe: {BOOK_PATH}")
        return {}
    log("Libro agronómico encontrado", True, f"{BOOK_PATH} ({BOOK_PATH.stat().st_size} bytes)")

    if use_http:
        result = http_post_multipart(
            "/api/documents/ingest",
            BOOK_PATH,
            {
                "license": "institutional",
                "classification": "Publico",
                "title": "Manual Agronomico Integral del Maiz en Sistema MILPA",
                "author": "Equipo agronomico MILPA",
                "year": "2026",
            },
            timeout=600,
        )
        ok = isinstance(result, dict) and result.get("status") == "ok"
        log("/api/documents/ingest respondió OK", ok, json.dumps(result, ensure_ascii=False)[:300])
        # rebuild explícito por seguridad
        rebuild = http_post("/api/index/rebuild", {}, timeout=600)
        rebuild_ok = (
            isinstance(rebuild, dict)
            and rebuild.get("status") in {"ok", "success"}
            and any(k.startswith("indexed") or k.endswith("_docs") for k in rebuild.keys())
        )
        log("/api/index/rebuild ejecutado", rebuild_ok,
            json.dumps(rebuild, ensure_ascii=False)[:200])
        return result if isinstance(result, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# 4. Pipeline RAG (in-process si no hay backend)
# ---------------------------------------------------------------------------

def call_recommendation(crop_id: int, use_http: bool) -> Dict[str, Any]:
    payload = {"user_crop_id": crop_id}
    if use_http:
        result = http_post("/api/recommendations/generate", payload, timeout=300)
        return result if isinstance(result, dict) else {"_error": "respuesta inválida"}

    # Fallback in-process
    sys.path.insert(0, str(ROOT))
    try:
        from milpa_ai_backend.api.crops import generate_recommendation, RecommendationRequest  # type: ignore
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            generate_recommendation(RecommendationRequest(user_crop_id=crop_id))
        ).model_dump()  # type: ignore[attr-defined]
    except Exception as exc:
        return {"_error": f"in-process error: {exc}"}


def call_query(question: str, use_http: bool) -> Dict[str, Any]:
    if use_http:
        result = http_post("/api/query", {"query": question, "k": 6, "mode": "hybrid"}, timeout=180)
        return result if isinstance(result, dict) else {"_error": "respuesta inválida"}
    return {"_error": "modo http requerido para /api/query"}


# ---------------------------------------------------------------------------
# 5. Validación
# ---------------------------------------------------------------------------

def verify_recommendation(conn: sqlite3.Connection, crop_id: int, recommendation: Dict[str, Any]) -> None:
    if not isinstance(recommendation, dict) or recommendation.get("_error"):
        log("Recomendación generada por el pipeline", False, str(recommendation))
        return

    log("Recomendación generada por el pipeline", True, f"action={recommendation.get('action')} priority={recommendation.get('priority')}")

    expected_actions = ("riego urgente", "proteger del calor", "programar riego", "sombra o acolchado", "riego")
    action = (recommendation.get("action") or "").lower()
    log("Acción coherente con caso 'maíz + 35-37°C + suelo 22%'",
        any(token in action for token in expected_actions),
        f"action='{action}'")

    log("Prioridad alta o media (caso de estrés)",
        (recommendation.get("priority") or "").lower() in {"high", "medium"},
        f"priority='{recommendation.get('priority')}'")

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM recommendations WHERE user_crop_id = ?", (crop_id,))
    cnt = cur.fetchone()[0]
    log("Recomendación persistida en tabla `recommendations`", cnt > 0, f"filas={cnt}")

    detail = recommendation.get("detail_html") or ""
    log("La recomendación tiene cuerpo agronómico (>50 caracteres)",
        len(detail) > 50, f"len={len(detail)}")

    citations = recommendation.get("citations")
    has_citations = False
    try:
        cit = json.loads(citations) if isinstance(citations, str) else citations
        has_citations = isinstance(cit, list) and len(cit) > 0
    except Exception:
        has_citations = False
    log("Recomendación contiene citas del RAG (preferible)", has_citations, f"citations={citations}")


def verify_library(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM docs")
    docs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM fragments")
    frags = cur.fetchone()[0]
    log("Biblioteca con documentos suficientes (>1)", docs > 1, f"docs={docs}")
    log("Biblioteca con fragmentos para RAG (>20)", frags > 20, f"fragments={frags}")
    cur.execute("SELECT COUNT(*) FROM faqs")
    faqs = cur.fetchone()[0]
    log("Tabla `faqs` poblada (>=5)", faqs >= 5, f"faqs={faqs}")
    cur.execute("SELECT COUNT(*) FROM library_categories")
    cats = cur.fetchone()[0]
    log("Tabla `library_categories` poblada (==4)", cats == 4, f"cats={cats}")


def verify_extra_query(use_http: bool) -> None:
    if not use_http:
        return
    sample_q = "que hago si el maiz tiene 37 grados y humedad de suelo 22 por ciento en floracion"
    res = call_query(sample_q, use_http=True)
    if not isinstance(res, dict) or res.get("_error"):
        log("/api/query respondió", False, str(res)[:200])
        return
    insufficient = res.get("insufficient_evidence")
    log("/api/query no marca evidencia insuficiente",
        not insufficient,
        f"insufficient_evidence={insufficient} fragmentos={res.get('total_retrieved')}")
    answer = (res.get("answer") or "").lower()
    log("Respuesta menciona 'riego' o 'sombra' o 'acolchado'",
        any(t in answer for t in ("riego", "sombra", "acolchado", "humedad")),
        f"answer[:200]={answer[:200]}")


def verify_frontend_endpoints(user_id: int, crop_id: int, use_http: bool) -> None:
    """Verifica los endpoints FastAPI que alimentan la UI con datos dinámicos.

    Las rutas /api/library/categories y /api/faqs viven en el servidor Express
    (frontend/routes/api.js) detrás de JWT, por eso aquí no se prueban en HTTP;
    su contenido se valida vía conteo en SQLite en `verify_library()`.
    """
    if not use_http:
        return
    crops = http_get(f"/api/crops/{user_id}")
    has_xy = (
        isinstance(crops, list)
        and any(("sensor_x_pct" in c and "sensor_y_pct" in c) for c in crops)
    )
    log("/api/crops expone sensor_x_pct / sensor_y_pct (mapa tiempo-real)", has_xy,
        f"crops={len(crops) if isinstance(crops, list) else 'n/a'}")

    eff = http_get(f"/api/irrigation-events/{crop_id}/efficiency")
    eff_ok = (
        isinstance(eff, dict)
        and isinstance(eff.get("optimal_values"), list)
        and len(eff.get("optimal_values") or []) == 5
        and isinstance(eff.get("optimal_targets"), dict)
    )
    log("/api/irrigation-events/:id/efficiency con radar y targets dinámicos (datos.html)", eff_ok,
        f"radar={eff.get('optimal_values') if isinstance(eff, dict) else 'n/a'} targets={eff.get('optimal_targets') if isinstance(eff, dict) else 'n/a'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def backend_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND}/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-http", action="store_true", help="Forzar modo in-process sin llamar al backend HTTP")
    args = parser.parse_args()

    print(f"\n=== MILPA E2E TEST · {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"DB:      {DB_PATH}")
    print(f"Backend: {BACKEND}")

    use_http = (not args.no_http) and backend_alive()
    log("Backend HTTP disponible", use_http, BACKEND if use_http else "se usará pipeline in-process")

    run_migrations()

    if not DB_PATH.exists():
        log("Base de datos accesible", False, f"no existe {DB_PATH}")
        return 1
    log("Base de datos accesible", True, f"{DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        seed = seed_demo(conn)
        log("Usuario y cultivo demo listos", True, json.dumps(seed))

        ingest_book(use_http=use_http)
        verify_library(conn)

        rec = call_recommendation(seed["crop_id"], use_http=use_http)
        verify_recommendation(conn, seed["crop_id"], rec if isinstance(rec, dict) else {})
        verify_extra_query(use_http=use_http)
        verify_frontend_endpoints(seed["user_id"], seed["crop_id"], use_http=use_http)
    finally:
        conn.close()

    print("\n--- CHECKLIST FINAL ---")
    passed = sum(1 for c in CHECKS if c["ok"])
    total = len(CHECKS)
    for c in CHECKS:
        flag = "OK" if c["ok"] else "FAIL"
        print(f"  [{flag}] {c['step']}")
    print(f"\nResultado: {passed}/{total} checks aprobados.")
    return 0 if passed == total else 2


if __name__ == "__main__":
    sys.exit(main())
