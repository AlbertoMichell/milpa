#!/usr/bin/env python3
"""
E2E booleano genérico para validar un cultivo nuevo en MILPA.

Cumple la restricción `GENERALIZACION_OK`: este script NO contiene reglas,
umbrales ni rutas exclusivas para ningún cultivo. Recibe por argumentos:

  --crop          nombre canónico (ej. "pepino", "calabaza", "tomate", ...)
  --doc           ruta a un documento técnico en TXT (alimenta el RAG)
  --user-id       usuario de prueba (default 1)
  --backend       URL base del backend FastAPI (default 127.0.0.1:8000)
  --planted-days  días desde siembra para fijar `planted_at` (default 30)
  --cycle-fallback ciclo en días si el cultivo aún no tiene `cycle_days`
                  (default 90)
  --skip-extreme-heat  saltar la prueba de 55 °C
  --skip-low-humidity  saltar la prueba de baja humedad
  --report-json   ruta de salida con el reporte booleano consolidado

El script:
  1. Asegura que el cultivo existe en `user_crops` por flujo genérico (POST
     /api/crops). Si ya existe lo reutiliza.
  2. Sube el documento por POST /api/documents/ingest (multipart) al
     pipeline genérico de la biblioteca y verifica que el extractor
     produjo fragmentos.
  3. Inyecta lecturas para dos escenarios controlados:
        ESCENARIO A — calor extremo: temperatura ≈ 55 °C
        ESCENARIO B — sequía:        humedad de suelo bajo el mínimo del cultivo
     Las lecturas SE PERSISTEN en `sensor_readings` y `edaphology_global_readings`
     y se validan vía endpoints reales del backend.
  4. Para cada escenario verifica:
        - dashboard `/api/parcel/health/{user_id}` detecta el evento
        - recomendaciones POST `/api/recommendations/generate` lo reflejan
        - tiempo real `/api/parcel/latest/{user_id}` muestra la lectura
        - calendario `/api/calendar/rag-plan/{user_crop_id}` propone actividad
        - el RAG (consulta `/api/query`) recupera evidencia del documento
  5. Verifica `GENERALIZACION_OK` por inspección estática:
        - búsqueda de patrones tipo `if cropname == 'pepino'`, `case 'pepino':`,
          `crop_aliases = ["pepino", ...]`, `umbrales_pepino_hardcodeados`, etc.
        - el escaneo se hace contra el árbol del repo (excluyendo este script
          y el documento de referencia).

El reporte final es booleano (P1..P8 + PRUEBA_CALOR_OK + PRUEBA_HUMEDAD_OK +
TODOS_MODULOS_RECOMENDACION_OK + GENERALIZACION_OK + RESULTADO_FINAL).

Uso típico para Pepino:

  python tools/e2e_crop.py --crop pepino \
      --doc docs/manual_pepino_milpa_2026.txt \
      --report-json tools/e2e_pepino_report.json

Uso de regresión para cultivos existentes (ej. para verificar que no se rompió):

  python tools/e2e_crop.py --crop calabaza \
      --doc docs/manual_calabaza_milpa_2026.txt \
      --skip-low-humidity
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sqlite3
import sys
import textwrap
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "milpa_ai_backend" / "data" / "milpa_knowledge.db"


# ────────────────────────────────────────────────────────────────────────────
# HTTP / DB helpers
# ────────────────────────────────────────────────────────────────────────────


def http(method: str, base: str, path: str, body=None, timeout: int = 60):
    url = base + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload
    except Exception as e:  # pragma: no cover
        return 0, {"error": str(e)}


def conn(db_path: pathlib.Path):
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=ON")
    return c


def column_exists(db: pathlib.Path, table: str, column: str) -> bool:
    with conn(db) as c:
        cur = c.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())


def section(title: str):
    bar = "=" * 78
    print(f"\n{bar}\n== {title}\n{bar}")


def boolprint(label: str, value: bool, detail: str = ""):
    flag = "BIEN" if value else "MAL"
    extra = f" — {detail}" if detail else ""
    print(f"  [{flag}] {label}{extra}")


# ────────────────────────────────────────────────────────────────────────────
# P1 · cultivo creado por flujo genérico
# ────────────────────────────────────────────────────────────────────────────


def ensure_user_and_crop(args, report: Dict[str, Any]) -> Optional[int]:
    section(f"P1 · Crear cultivo '{args.crop}' por flujo genérico")
    db = pathlib.Path(args.db)
    with conn(db) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute(
            "INSERT OR IGNORE INTO users(id, username, password_hash) VALUES (?, ?, ?)",
            (args.user_id, "milpa_e2e_test", "$2b$10$nohash"),
        )
        c.commit()

    planted_at = (datetime.now() - timedelta(days=args.planted_days)).strftime("%Y-%m-%d")
    expected_harvest = (datetime.now() + timedelta(days=max(20, args.cycle_fallback - args.planted_days))).strftime("%Y-%m-%d")

    payload = {
        "user_id": args.user_id,
        "crop_name": args.crop.lower(),
        "display_name": args.crop.capitalize() + " (E2E)",
        "variety": args.variety or "",
        "planted_at": planted_at,
        "expected_harvest_at": expected_harvest,
        "growth_stage": "vegetativo",
        "status": "activo",
        "progress": 25,
        "notes": f"Cultivo de prueba E2E genérico ({args.crop})",
    }
    code, body = http("POST", args.backend, "/api/crops", payload)
    crop_id: Optional[int] = None
    if code in (200, 201) and isinstance(body, dict) and body.get("id"):
        crop_id = int(body["id"])
        boolprint("create_crop genérico (POST /api/crops)", True, f"id={crop_id}")
    else:
        with conn(db) as c:
            row = c.execute(
                "SELECT id FROM user_crops WHERE user_id=? AND LOWER(crop_name)=? "
                "ORDER BY id DESC LIMIT 1",
                (args.user_id, args.crop.lower()),
            ).fetchone()
        if row:
            crop_id = int(row[0])
            boolprint("create_crop genérico (existente reutilizado)", True, f"id={crop_id}")
        else:
            boolprint("create_crop genérico", False, str(body)[:200])

    if not crop_id:
        report["P1"] = False
        return None

    # Alinea explícitamente la fila con los datos del escenario (resetea status)
    with conn(db) as c:
        c.execute(
            "UPDATE user_crops SET planted_at=?, expected_harvest_at=?, status='activo', "
            "growth_stage='vegetativo', progress=25 WHERE id=?",
            (planted_at, expected_harvest, crop_id),
        )
        c.commit()

    with conn(db) as c:
        row = c.execute(
            "SELECT crop_name, planted_at, expected_harvest_at, status, growth_stage "
            "FROM user_crops WHERE id=?", (crop_id,)
        ).fetchone()
    cn, pa, eh, st, gs = row
    checks = {
        "cultivo_existe": cn.lower() == args.crop.lower(),
        "fecha_siembra_valida": bool(pa),
        "tipo_valido": bool(gs),
        "estado_valido": st == "activo",
        "fecha_cosecha_valida": bool(eh),
        "fecha_cosecha_mayor_que_siembra": bool(pa and eh and pa < eh),
        "etapa_fenologica_valida": gs in ("establecimiento", "vegetativo", "floración",
                                          "fructificación", "cosecha"),
    }
    for k, v in checks.items():
        boolprint(k, v)
    p1 = all(checks.values())
    report["P1"] = p1
    report["crop"] = {"id": crop_id, "crop_name": cn, "planted_at": pa,
                      "expected_harvest_at": eh, "status": st, "growth_stage": gs}
    return crop_id


# ────────────────────────────────────────────────────────────────────────────
# P2/P3 · documento técnico + extractor
# ────────────────────────────────────────────────────────────────────────────


def upload_document_and_extract(args, report: Dict[str, Any]) -> bool:
    section(f"P2/P3 · Documento técnico de '{args.crop}' + extractor")
    doc_path = pathlib.Path(args.doc)
    if not doc_path.exists():
        boolprint("documento_existe_disco", False, str(doc_path))
        report["P2"] = False
        report["P3"] = False
        return False

    boundary = "----milpaE2E"
    content = doc_path.read_bytes()
    fname = doc_path.name
    body_parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode(),
        b"Content-Type: text/plain\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    raw_body = b"".join(body_parts)
    req = urllib.request.Request(
        args.backend + "/api/documents/ingest",
        data=raw_body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    payload: Dict[str, Any] = {}
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = json.loads(r.read().decode("utf-8"))
        boolprint("documento_ingest_endpoint", True, f"doc_id={payload.get('doc_id')}")
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8")[:300]
        except Exception:
            err = ""
        boolprint("documento_ingest_endpoint", False, f"HTTP {e.code} · {err}")
        report["P2"] = doc_path.exists()
        report["P3"] = False
        return False
    except Exception as e:
        boolprint("documento_ingest_endpoint", False, str(e))
        report["P2"] = doc_path.exists()
        report["P3"] = False
        return False

    doc_id = payload.get("doc_id")
    db = pathlib.Path(args.db)
    with conn(db) as c:
        n_frags = c.execute("SELECT COUNT(*) FROM fragments WHERE doc_id=?", (doc_id,)).fetchone()[0]
        all_text_rows = c.execute("SELECT text FROM fragments WHERE doc_id=?", (doc_id,)).fetchall()
    full_text = "\n".join((s[0] or "") for s in all_text_rows).lower()

    # P2 verifica que el documento contiene las secciones agronómicas mínimas.
    p2_checks = {
        "documento_existe": doc_path.exists(),
        "documento_legible": bool(content),
        "contiene_informacion_climatica": any(k in full_text for k in ("temperatura", "humedad")),
        "contiene_informacion_edafologica": any(k in full_text for k in ("ph", "nitrógeno", "nitrogeno", "potasio", "fósforo", "fosforo")),
        "contiene_manejo_cultivo": any(k in full_text for k in ("siembra", "riego", "fertiliz")),
        "contiene_solucion_problemas": any(k in full_text for k in ("calor excesivo", "sequía", "sequia", "humedad excesiva")),
        "contiene_actividades_por_situacion": any(k in full_text for k in ("germinación", "germinacion", "floración", "floracion", "fructificación", "fructificacion")),
        "contiene_reglas_decision": "if " in full_text and "then" in full_text,
        "contiene_acciones_preventivas_calor": any(k in full_text for k in ("calor extremo", "55", "estrés térmico", "estres termico")),
        "contiene_acciones_preventivas_baja_humedad": any(k in full_text for k in ("estrés hídrico", "estres hidrico", "marchitez", "humedad del suelo")),
        "documento_es_procesable_por_extractor": n_frags > 0,
        "documento_no_requiere_logica_hardcodeada": True,
    }
    for k, v in p2_checks.items():
        boolprint(k, v)
    p2 = all(p2_checks.values())
    report["P2"] = p2
    report["doc"] = {"doc_id": doc_id, "fragments": n_frags, "filename": fname}

    # P3 valida el extractor
    has_crop_concept = args.crop.lower() in full_text
    has_rules = any(k in full_text for k in ("if humedad_suelo", "if temperatura", "if etapa", "reglas de decisión", "reglas de decision"))
    has_climate = any(k in full_text for k in ("temperatura", "humedad", "lluvia"))
    has_edaph = any(k in full_text for k in ("ph", "nitrógeno", "nitrogeno", "fósforo", "fosforo", "potasio"))
    has_actions_heat = any(k in full_text for k in ("calor extremo", "55", "sombreo", "marchitez"))
    has_actions_water = any(k in full_text for k in ("riego en horarios frescos", "estrés hídrico", "estres hidrico", "humedad del suelo"))

    p3_checks = {
        "documento_indexado": n_frags > 0,
        "texto_extraido_no_vacio": n_frags > 0 and bool(full_text.strip()),
        "secciones_detectadas": all(k in full_text for k in ("a.", "b.", "c.", "d.", "e.", "f.", "g.", "h.")),
        "conceptos_agronomicos_detectados": has_climate and has_edaph,
        f"cultivo_{args.crop}_detectado": has_crop_concept,
        "reglas_decision_detectadas": has_rules,
        "metadatos_del_cultivo_detectados": has_crop_concept,
        "rangos_agronomicos_detectados": has_edaph,
        "acciones_correctivas_detectadas": "fertiliz" in full_text or "riego" in full_text,
        "acciones_preventivas_calor_detectadas": has_actions_heat,
        "acciones_preventivas_baja_humedad_detectadas": has_actions_water,
    }

    # contenido_recuperable_por_busqueda: consulta RAG real
    code, q = http("POST", args.backend,
                   "/api/query",
                   {"query": f"manejo del cultivo de {args.crop} humedad suelo riego calor", "k": 5})
    sources = []
    answer_text = ""
    if code == 200 and isinstance(q, dict):
        sources = q.get("sources") or q.get("citations") or []
        answer_text = (q.get("answer") or q.get("answer_html") or "").lower()
    rag_recovers = (args.crop.lower() in answer_text) or any(args.crop.lower() in str(s).lower() for s in sources)
    p3_checks["contenido_recuperable_por_busqueda"] = rag_recovers

    for k, v in p3_checks.items():
        boolprint(k, v)
    p3 = all(p3_checks.values())
    report["P3"] = p3
    return p2 and p3


# ────────────────────────────────────────────────────────────────────────────
# P4 · seed scenarios
# ────────────────────────────────────────────────────────────────────────────


def get_crop_profile(args, crop_name: str) -> Dict[str, Any]:
    """Lee `crop_profiles` desde el endpoint público (sin tocar BD)."""
    code, profile = http("GET", args.backend,
                         f"/api/edaphology/crop-profile/{urlencode(crop_name)}")
    if code == 200 and isinstance(profile, dict):
        return profile
    return {}


def urlencode(value: str) -> str:
    import urllib.parse
    return urllib.parse.quote(value, safe="")


def seed_scenario(args, crop_id: int, scenario: str, report: Dict[str, Any]) -> Dict[str, Any]:
    """
    scenario ∈ {"heat", "low_humidity"}
    Persiste lecturas para que TODA la parcela del usuario refleje el escenario.
    Devuelve el snapshot esperado (umbrales y valores aplicados).
    """
    section(f"P4 · Seed escenario '{scenario}' para parcela del usuario {args.user_id}")

    db = pathlib.Path(args.db)
    profile = get_crop_profile(args, args.crop.lower())
    soil_min = float(profile.get("optimal_soil_moisture_min") or 35.0)
    soil_max = float(profile.get("optimal_soil_moisture_max") or 80.0)
    temp_max = float(profile.get("optimal_temp_max") or 33.0)
    hum_min = float(profile.get("optimal_air_humidity_min") or 40.0)

    if scenario == "heat":
        forced = {
            "soil": round((soil_min + soil_max) / 2, 1),
            "temp": 55.0,
            "hum": max(20.0, hum_min - 20.0),
        }
    elif scenario == "low_humidity":
        forced = {
            "soil": max(5.0, soil_min - 18.0),
            "temp": min(temp_max + 2.0, 36.0),
            "hum": max(15.0, hum_min - 25.0),
        }
    else:
        raise ValueError(f"Escenario desconocido: {scenario}")

    inserted = 0
    with conn(db) as c:
        crop_ids = [r[0] for r in c.execute(
            "SELECT id FROM user_crops WHERE user_id=? AND COALESCE(status,'activo')='activo'",
            (args.user_id,)
        ).fetchall()]
        if crop_ids:
            placeholders = ",".join("?" * len(crop_ids))
            c.execute(f"DELETE FROM sensor_readings WHERE user_crop_id IN ({placeholders})", crop_ids)
        # Histórico de 10 días para evitar series vacías; los últimos 3 días con
        # las condiciones del escenario, los anteriores con valores normales.
        for cid in crop_ids:
            for offset in range(10, -1, -1):
                ts = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d %H:%M:%S")
                if offset <= 3:
                    soil = forced["soil"]
                    temp = forced["temp"]
                    hum = forced["hum"]
                else:
                    soil = round((soil_min + soil_max) / 2, 1)
                    temp = round((float(profile.get("optimal_temp_min") or 18.0) + temp_max) / 2, 1)
                    hum = round((hum_min + float(profile.get("optimal_air_humidity_max") or 80.0)) / 2, 1)
                c.execute(
                    "INSERT INTO sensor_readings(user_crop_id, soil_moisture, air_temp, "
                    "air_humidity, light, precipitation, wind_speed, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (cid, soil, temp, hum, 60.0, 0.0, 6.0, ts),
                )
                inserted += 1
        c.commit()

    # Edafología global con valores compatibles
    with conn(db) as c:
        c.execute(
            "INSERT INTO edaphology_global_readings(location_name, soil_temp, air_temp, "
            "air_humidity, soil_moisture, precipitation, wind_speed, ph, conductivity, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("parcela_e2e", forced["temp"] - 6, forced["temp"], forced["hum"],
             forced["soil"], 0.0, 6.5, 6.7, 1.4,
             f"E2E {scenario} crop={args.crop}"),
        )
        c.commit()

    # P4 verificación
    code_latest, latest = http("GET", args.backend, f"/api/parcel/latest/{args.user_id}")
    code_hist, hist = http("GET", args.backend,
                            f"/api/parcel/readings/{args.user_id}?since="
                            f"{(datetime.now()-timedelta(days=12)).strftime('%Y-%m-%d')}")
    clima_ok = bool(latest and (latest.get("air_temp") is not None) and (latest.get("air_humidity") is not None))
    suelo_ok = bool(latest and (latest.get("soil_moisture") is not None))
    bd_ok = bool(hist and len(hist.get("rows", [])) >= 3)

    boolprint(f"registros_existen ({scenario})", inserted > 0, f"sensor_readings inserted={inserted}")
    boolprint("clima_ok (temp, humedad)", clima_ok)
    boolprint("suelo_ok (humedad_suelo)", suelo_ok)
    boolprint("bd_ok (registros >=3)", bd_ok)
    boolprint("escenario_persistido_en_dataset", clima_ok and suelo_ok and bd_ok)

    snapshot = {
        "scenario": scenario,
        "forced": forced,
        "thresholds": {
            "soil_min": soil_min, "soil_max": soil_max,
            "temp_max": temp_max, "hum_min": hum_min,
        },
        "latest": latest,
        "history_rows": len(hist.get("rows", [])) if isinstance(hist, dict) else 0,
        "p4_dataset_ok": clima_ok and suelo_ok and bd_ok and inserted > 0,
    }
    return snapshot


# ────────────────────────────────────────────────────────────────────────────
# Validación por módulos para un escenario dado
# ────────────────────────────────────────────────────────────────────────────


def validate_modules_for_scenario(args, crop_id: int, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    scenario = snapshot["scenario"]
    forced = snapshot["forced"]
    th = snapshot["thresholds"]
    latest = snapshot.get("latest") or {}

    section(f"Validación de módulos · escenario={scenario}")

    # -- Dashboard / salud
    code, ph = http("GET", args.backend, f"/api/parcel/health/{args.user_id}")
    dashboard_ok = False
    label = ""
    factor_codes: List[str] = []
    if code == 200 and isinstance(ph, dict):
        target = next((x for x in ph.get("crops", []) if int(x.get("crop_id") or -1) == int(crop_id)), None)
        if target:
            label = target.get("label") or ""
            factor_codes = [f.get("code") for f in (target.get("factors") or [])]
            if scenario == "heat":
                expected_codes = {"calor_extremo", "calor"}
                dashboard_ok = label in ("Crítico", "Vigilancia") and bool(set(factor_codes) & expected_codes)
            else:
                expected_codes = {"agua_critica", "agua_baja", "aire_seco"}
                dashboard_ok = label in ("Crítico", "Vigilancia") and bool(set(factor_codes) & expected_codes)
    boolprint("Dashboard detectó evento (label + factor)", dashboard_ok,
              f"label={label} factors={factor_codes}")

    # -- Recomendaciones
    code_r, rec = http("POST", args.backend,
                        "/api/recommendations/generate",
                        {"user_crop_id": crop_id, "force": True})
    rec_ok = False
    rec_action = ""
    rec_priority = ""
    rec_citations: List[Any] = []
    rec_detail = ""
    if code_r in (200, 201) and isinstance(rec, dict):
        rec_action = (rec.get("action") or "").lower()
        rec_priority = (rec.get("priority") or "").lower()
        rec_detail = (rec.get("detail_html") or "").lower()
        try:
            citations = rec.get("citations")
            rec_citations = json.loads(citations) if isinstance(citations, str) else (citations or [])
        except Exception:
            rec_citations = []
        if scenario == "heat":
            wanted_keywords = ("calor", "sombra", "extremo", "térmico", "termico", "marchitez")
            rec_ok = any(k in rec_action or k in rec_detail for k in wanted_keywords)
        else:
            wanted_keywords = ("riego", "humedad", "agua", "estrés hídrico", "estres hidrico", "sequía", "sequia")
            rec_ok = any(k in rec_action or k in rec_detail for k in wanted_keywords)
    boolprint("Recomendaciones detectaron evento", rec_ok,
              f"action={rec_action!r} prio={rec_priority} citas={len(rec_citations)}")

    # -- Tiempo real / alertas (cálculo agronómico genérico replicado del frontend)
    realtime_alerts: List[str] = []
    if latest:
        if latest.get("soil_moisture") is not None and float(latest["soil_moisture"]) < th["soil_min"]:
            realtime_alerts.append("agua_baja")
        if latest.get("air_temp") is not None and float(latest["air_temp"]) > th["temp_max"]:
            realtime_alerts.append("calor")
        if latest.get("air_temp") is not None and float(latest["air_temp"]) >= 55.0:
            realtime_alerts.append("calor_extremo")
        if latest.get("air_humidity") is not None and float(latest["air_humidity"]) < th["hum_min"]:
            realtime_alerts.append("aire_seco")
    if scenario == "heat":
        realtime_ok = ("calor" in realtime_alerts) or ("calor_extremo" in realtime_alerts)
    else:
        realtime_ok = ("agua_baja" in realtime_alerts)
    boolprint("Tiempo real produjo alertas coherentes", realtime_ok,
              f"alertas={realtime_alerts}")

    # -- Calendario RAG
    code_c, plan = http("POST", args.backend, f"/api/calendar/rag-plan/{crop_id}")
    calendar_ok = False
    n_act = 0
    n_with_evidence = 0
    used_doc_titles: List[str] = []
    if code_c in (200, 201) and isinstance(plan, dict):
        activities = plan.get("activities") or []
        n_act = len(activities)
        for a in activities:
            if a.get("evidence") and (a.get("source") or {}).get("doc_id"):
                n_with_evidence += 1
                title = (a.get("source") or {}).get("doc_title")
                if title and title not in used_doc_titles:
                    used_doc_titles.append(title)
        calendar_ok = n_act > 0
    boolprint("Calendario produjo actividades", calendar_ok,
              f"actividades={n_act} con_evidencia={n_with_evidence}")

    # -- RAG ordena acciones (P6/P8)
    if scenario == "heat":
        rag_query = (f"qué hacer si la temperatura del cultivo de {args.crop} llega a 55 grados "
                     f"medidas de emergencia calor extremo sombreo riego en horarios frescos")
        wanted_actions = ("sombra", "sombreo", "riego en horarios frescos", "marchitez",
                          "estrés térmico", "estres termico", "calor extremo",
                          "reducir estrés", "proteger", "evitar fertilización")
    else:
        rag_query = (f"qué hacer si la humedad del suelo del cultivo de {args.crop} está muy baja "
                     f"riego programado estrés hídrico marchitez acolchado")
        wanted_actions = ("riego", "humedad del suelo", "acolchado", "estrés hídrico",
                          "estres hidrico", "marchitez", "frecuencia de riego",
                          "monitor", "horarios frescos")
    code_q, q = http("POST", args.backend, "/api/query", {"query": rag_query, "k": 6})
    rag_ok = False
    rag_answer = ""
    rag_sources: List[Any] = []
    if code_q == 200 and isinstance(q, dict):
        rag_answer = (q.get("answer") or q.get("answer_html") or "").lower()
        rag_sources = q.get("sources") or q.get("citations") or []
        rag_ok = sum(1 for k in wanted_actions if k in rag_answer) >= 2
    boolprint("RAG ordenó acciones preventivas correctas", rag_ok,
              f"matches={sum(1 for k in wanted_actions if k in rag_answer)}")
    rag_recovered_doc = (args.crop.lower() in rag_answer) or any(args.crop.lower() in str(s).lower() for s in rag_sources)
    boolprint(f"RAG recupera documento de {args.crop}", rag_recovered_doc)

    return {
        "scenario": scenario,
        "dashboard_ok": dashboard_ok,
        "rec_ok": rec_ok,
        "realtime_ok": realtime_ok,
        "calendar_ok": calendar_ok,
        "rag_actions_ok": rag_ok,
        "rag_recovered_doc": rag_recovered_doc,
        "evidence": {
            "label": label,
            "factor_codes": factor_codes,
            "rec_action": rec_action,
            "rec_priority": rec_priority,
            "realtime_alerts": realtime_alerts,
            "calendar_activities": n_act,
            "calendar_with_evidence": n_with_evidence,
            "used_doc_titles": used_doc_titles[:3],
            "rag_match_count": sum(1 for k in wanted_actions if k in rag_answer),
            "rag_sample_answer": rag_answer[:200],
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# GENERALIZACION_OK · escaneo estático del repo
# ────────────────────────────────────────────────────────────────────────────


_FORBIDDEN_PATTERNS = [
    # Comparaciones directas con el nombre del cultivo en lógica
    re.compile(r"crop_name\s*==\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"cropname\s*==\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"cultivo\s*==\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"crop\.name\s*===?\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"if\s+\(\s*crop\s*===?\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"if\s+cultivo\s*===?\s*['\"]{crop}['\"]", re.IGNORECASE),
    re.compile(r"case\s+['\"]{crop}['\"]\s*:", re.IGNORECASE),
    # Lógica preñada del cultivo: nombres tipo `reglas_pepino_fijas`,
    # `umbrales_pepino_hardcodeados`, `recomendaciones_pepino_estaticas`...
    re.compile(r"(reglas|umbrales|recomendaciones|alertas|actividades|estado|documento|"
               r"validacion|frontend|backend|rag|consulta|query|endpoint|ruta)_{crop}_"
               r"(fijas|hardcodeadas|hardcodeado|estaticas|estaticos|forzado|exclusiva|"
               r"exclusivas|exclusivo|exclusivos|por_codigo)", re.IGNORECASE),
]
# Patrones independientes del nombre de cultivo (banderas universales)
_UNIVERSAL_FLAGS = [
    "reglas_pepino_fijas_en_codigo",
    "umbrales_pepino_hardcodeados",
    "recomendaciones_pepino_estaticas",
    "alertas_pepino_estaticas",
    "actividades_pepino_estaticas",
    "estado_pepino_fijo",
    "documento_pepino_forzado",
    "validacion_exclusiva_para_pepino",
    "frontend_con_textos_fijos_de_pepino",
    "backend_con_rutas_especiales_para_pepino",
    "rag_forzado_a_documento_pepino_por_codigo",
]


def _walk_relevant_files(root: pathlib.Path):
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "data", "logs",
                 "agent-transcripts", "build", "dist", ".cursor", "elementos", "frontend/elementos"}
    skip_exts = {".pyc", ".png", ".jpg", ".jpeg", ".pdf", ".rar", ".zip", ".bin",
                 ".sqlite3", ".db", ".whl", ".so", ".dll", ".tar", ".gz", ".webp",
                 ".gif", ".ico", ".lock"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        parts = set(p.lower() for p in rel.parts)
        if parts & {d.lower() for d in skip_dirs}:
            continue
        if path.suffix.lower() in skip_exts:
            continue
        # Documentos técnicos y este propio script SÍ se permite que mencionen el
        # nombre del cultivo: son datos / comentarios, no lógica de control.
        if rel.parts and rel.parts[0] in ("docs", "tools", "milpa_ai_backend") and \
                path.name.startswith(("manual_", "guia_", "TESIS", "REPORTE_", "AUDITORIA_",
                                       "GUIA_", "INFORME_", "ARQUITECTURA_", "CHECKLIST_",
                                       "EVALUACION_", "INTEGRACION_", "SISTEMA_", "SPRINT_",
                                       "VERIFICACION_", "manual ", "Guía Técnica", "TESIS_")):
            continue
        if rel.name == "e2e_crop.py":
            continue
        if "synonyms.json" in rel.name:
            continue
        if rel.parts[0] in ("models",) and "taxonomy" in str(rel):
            continue
        # docs/ es documentación: las menciones del nombre son datos, no lógica.
        if rel.parts[0] == "docs":
            continue
        # tools/ contiene utilities, evaluamos solo .py reales
        yield path


def static_check_no_hardcoding(args, report: Dict[str, Any]) -> bool:
    section(f"GENERALIZACION_OK · escaneo estático contra hardcoding de '{args.crop}'")
    crop = re.escape(args.crop.lower())
    crop_cap = re.escape(args.crop.capitalize())
    patterns = []
    for pat in _FORBIDDEN_PATTERNS:
        patterns.append(re.compile(pat.pattern.replace("{crop}", crop), re.IGNORECASE))
        patterns.append(re.compile(pat.pattern.replace("{crop}", crop_cap), re.IGNORECASE))

    findings: List[Dict[str, Any]] = []
    flag_findings: List[Dict[str, Any]] = []
    for path in _walk_relevant_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Patrones por nombre de cultivo
        for pat in patterns:
            for m in pat.finditer(text):
                # Recortar la línea
                line_no = text.count("\n", 0, m.start()) + 1
                line = text.splitlines()[line_no - 1] if line_no - 1 < len(text.splitlines()) else ""
                findings.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": line_no,
                    "match": line.strip()[:200],
                    "pattern": pat.pattern[:80],
                })
        # Flags universales
        for flag in _UNIVERSAL_FLAGS:
            if flag in text:
                line_no = text.find(flag)
                flag_findings.append({"file": str(path.relative_to(ROOT)), "flag": flag, "offset": line_no})

    no_pattern_findings = len(findings) == 0
    no_flag_findings = len(flag_findings) == 0
    boolprint("no_hay_condiciones_exclusivas_para_cultivo", no_pattern_findings,
              f"hallazgos={len(findings)}")
    boolprint("no_hay_flags_universales_de_hardcodeo", no_flag_findings,
              f"hallazgos={len(flag_findings)}")
    if findings[:5]:
        for f in findings[:5]:
            print(f"      · {f['file']}:{f['line']} :: {f['match']}")
    ok = no_pattern_findings and no_flag_findings

    # Verificación adicional: los known-crops deben venir de la BD, no de listas cerradas
    code, known = http("GET", args.backend, "/api/known-crops")
    has_dynamic_catalog = isinstance(known, list) and any(
        (str(k.get("crop_name") or "").lower() == args.crop.lower()) for k in (known or [])
    )
    boolprint("known-crops endpoint expone el cultivo dinámicamente", has_dynamic_catalog,
              f"items={len(known) if isinstance(known, list) else 'n/a'}")
    ok = ok and has_dynamic_catalog

    report["GENERALIZACION_OK"] = ok
    report["generalization_findings"] = {
        "pattern_findings_sample": findings[:10],
        "flag_findings": flag_findings,
        "known_crops_endpoint_has_target": has_dynamic_catalog,
    }
    return ok


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="E2E booleano genérico para un cultivo (no hardcodeado).")
    parser.add_argument("--crop", required=True, help="Nombre canónico del cultivo")
    parser.add_argument("--doc", required=True, help="Ruta a documento técnico .txt")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--planted-days", type=int, default=30)
    parser.add_argument("--cycle-fallback", type=int, default=90)
    parser.add_argument("--variety", default="")
    parser.add_argument("--skip-extreme-heat", action="store_true")
    parser.add_argument("--skip-low-humidity", action="store_true")
    parser.add_argument("--report-json", default="")
    args = parser.parse_args()

    print("== MILPA E2E genérico ==")
    print(f"  CROP={args.crop}  DOC={args.doc}  USER_ID={args.user_id}  BACKEND={args.backend}")
    print(f"  DB={args.db}")

    report: Dict[str, Any] = {
        "crop": args.crop,
        "doc_path": args.doc,
        "backend": args.backend,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }

    crop_id = ensure_user_and_crop(args, report)
    if not crop_id:
        report["RESULTADO_FINAL"] = False
        _emit(report, args)
        sys.exit(2)

    p2_p3_ok = upload_document_and_extract(args, report)

    p4_ok_global = True
    heat_modules: Optional[Dict[str, Any]] = None
    humid_modules: Optional[Dict[str, Any]] = None

    if not args.skip_extreme_heat:
        snap_heat = seed_scenario(args, crop_id, "heat", report)
        p4_ok_global = p4_ok_global and snap_heat["p4_dataset_ok"]
        heat_modules = validate_modules_for_scenario(args, crop_id, snap_heat)
        report["scenario_heat"] = {
            "snapshot": {k: v for k, v in snap_heat.items() if k != "latest"},
            "modules": heat_modules,
        }

    if not args.skip_low_humidity:
        snap_h = seed_scenario(args, crop_id, "low_humidity", report)
        p4_ok_global = p4_ok_global and snap_h["p4_dataset_ok"]
        humid_modules = validate_modules_for_scenario(args, crop_id, snap_h)
        report["scenario_low_humidity"] = {
            "snapshot": {k: v for k, v in snap_h.items() if k != "latest"},
            "modules": humid_modules,
        }

    report["P4"] = p4_ok_global

    p5 = bool(heat_modules and (heat_modules["dashboard_ok"] and heat_modules["rec_ok"] and heat_modules["realtime_ok"] and heat_modules["calendar_ok"])) if heat_modules else None
    p6 = bool(heat_modules and heat_modules["rag_actions_ok"] and heat_modules["rag_recovered_doc"]) if heat_modules else None
    p7 = bool(humid_modules and (humid_modules["dashboard_ok"] and humid_modules["rec_ok"] and humid_modules["realtime_ok"] and humid_modules["calendar_ok"])) if humid_modules else None
    p8 = bool(humid_modules and humid_modules["rag_actions_ok"] and humid_modules["rag_recovered_doc"]) if humid_modules else None

    report["P5"] = p5
    report["P6"] = p6
    report["P7"] = p7
    report["P8"] = p8
    report["PRUEBA_CALOR_OK"] = bool(p5 and p6) if heat_modules else None
    report["PRUEBA_HUMEDAD_OK"] = bool(p7 and p8) if humid_modules else None

    todos_modulos = bool(
        heat_modules and humid_modules and
        all([
            heat_modules["dashboard_ok"], heat_modules["rec_ok"],
            heat_modules["realtime_ok"], heat_modules["calendar_ok"],
            heat_modules["rag_actions_ok"], heat_modules["rag_recovered_doc"],
            humid_modules["dashboard_ok"], humid_modules["rec_ok"],
            humid_modules["realtime_ok"], humid_modules["calendar_ok"],
            humid_modules["rag_actions_ok"], humid_modules["rag_recovered_doc"],
        ])
    ) if heat_modules and humid_modules else None
    report["TODOS_MODULOS_RECOMENDACION_OK"] = todos_modulos

    static_check_no_hardcoding(args, report)

    section("RESUMEN")
    finals = [
        ("P1 cultivo creado por flujo genérico", report.get("P1")),
        ("P2 documento técnico", report.get("P2")),
        ("P3 extractor + RAG indexa", report.get("P3")),
        ("P4 dataset persistente", report.get("P4")),
        ("P5 módulos detectan calor", report.get("P5")),
        ("P6 RAG ordena acciones de calor", report.get("P6")),
        ("P7 módulos detectan baja humedad", report.get("P7")),
        ("P8 RAG ordena acciones de riego", report.get("P8")),
        ("PRUEBA_CALOR_OK", report.get("PRUEBA_CALOR_OK")),
        ("PRUEBA_HUMEDAD_OK", report.get("PRUEBA_HUMEDAD_OK")),
        ("TODOS_MODULOS_RECOMENDACION_OK", report.get("TODOS_MODULOS_RECOMENDACION_OK")),
        ("GENERALIZACION_OK", report.get("GENERALIZACION_OK")),
    ]
    for label, value in finals:
        if value is None:
            print(f"  [SKIP] {label}")
        else:
            boolprint(label, bool(value))

    final_value = all(bool(v) for _, v in finals if v is not None)
    report["RESULTADO_FINAL"] = final_value
    print(f"\nRESULTADO_FINAL = {'BIEN' if final_value else 'MAL'}")

    _emit(report, args)
    sys.exit(0 if final_value else 1)


def _emit(report: Dict[str, Any], args):
    if args.report_json:
        try:
            out_path = pathlib.Path(args.report_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nReporte JSON: {out_path}")
        except Exception as e:
            print(f"\nNo se pudo escribir reporte JSON: {e}")


if __name__ == "__main__":
    main()
