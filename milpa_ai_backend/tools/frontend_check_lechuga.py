"""Verifica que las páginas del frontend (puerto 4000) cargan y que los endpoints
clave devuelven datos coherentes para el cultivo Lechuga creado por el E2E.

Uso:
    py -3 milpa_ai_backend/tools/frontend_check_lechuga.py
"""
from __future__ import annotations

import json
import urllib.request


FE = "http://127.0.0.1:4000"
BE = "http://127.0.0.1:8000"


def get_html(path: str) -> tuple[int, int]:
    r = urllib.request.urlopen(FE + path, timeout=10)
    return r.status, len(r.read())


def get_json(url: str) -> object:
    r = urllib.request.urlopen(url, timeout=20)
    return json.loads(r.read())


def post_json(url: str) -> object:
    req = urllib.request.Request(
        url, method="POST", headers={"Content-Type": "application/json"}, data=b"{}"
    )
    r = urllib.request.urlopen(req, timeout=30)
    return json.loads(r.read())


def find_lechuga_crop_id(user_id: int = 1) -> int | None:
    crops = get_json(f"{BE}/api/crops/{user_id}")
    if not isinstance(crops, list):
        return None
    for c in crops:
        if (c.get("crop_name") or "").lower() == "lechuga":
            return c.get("id")
    return None


def main() -> int:
    print("=== Frontend HTML pages (port 4000) ===")
    for path in ("/login.html", "/dashboard.html", "/recomendaciones.html", "/tiempo-real.html", "/calendario.html"):
        try:
            code, length = get_html(path)
            print(f"  {path:30s} HTTP {code} ({length} bytes)")
        except Exception as exc:
            print(f"  {path:30s} FAIL {exc}")

    crop_id = find_lechuga_crop_id(1)
    print(f"\n=== Lechuga crop_id (user 1) = {crop_id} ===")
    if crop_id is None:
        print("  No hay cultivo lechuga en user_crops. Aborto.")
        return 1

    print("\n=== /api/parcel/health/1 -> Lechuga ===")
    ph = get_json(f"{BE}/api/parcel/health/1")
    target = next((c for c in ph.get("crops", []) if c.get("crop_id") == crop_id), None)
    if target:
        print(f"  label    = {target.get('label')}")
        print(f"  status   = {target.get('status')}")
        print(f"  factors  = {[f.get('code') for f in target.get('factors') or []]}")
        print(f"  evidence = soil={target.get('latest', {}).get('soil_moisture')} "
              f"temp={target.get('latest', {}).get('air_temp')} "
              f"hum={target.get('latest', {}).get('air_humidity')}")
    else:
        print("  WARN: lechuga no aparece en /api/parcel/health/1")

    print("\n=== /api/recommendations/user/1 -> Lechuga ===")
    recs = get_json(f"{BE}/api/recommendations/user/1")
    recs_lechuga = [r for r in (recs or []) if r.get("user_crop_id") == crop_id]
    print(f"  count = {len(recs_lechuga)}")
    if recs_lechuga:
        r = recs_lechuga[0]
        print(f"  action     = {r.get('action')}")
        print(f"  priority   = {r.get('priority')}")
        cits = r.get("citations") or "[]"
        if isinstance(cits, str):
            try:
                cits = json.loads(cits)
            except Exception:
                cits = []
        print(f"  citations  = {len(cits) if isinstance(cits, list) else 'n/a'}")
        if isinstance(cits, list) and cits:
            for ci in cits[:3]:
                if isinstance(ci, dict):
                    print(f"    · doc={ci.get('doc_title') or ci.get('doc_id', '')[:12]} page={ci.get('page')}")
                else:
                    print(f"    · {ci}")

    print(f"\n=== /api/calendar/rag-plan/{crop_id} ===")
    plan = post_json(f"{BE}/api/calendar/rag-plan/{crop_id}")
    acts = plan.get("activities", []) if isinstance(plan, dict) else []
    print(f"  activities = {len(acts)}")
    for a in acts[:5]:
        title = (a.get("title") or "")[:60]
        ev = "Y" if a.get("evidence") else "N"
        src = (a.get("source") or {}).get("doc_title", "")[:30]
        print(f"    · ev={ev} title={title} doc={src}")

    print(f"\n=== /api/parcel/latest/1 -> condiciones actuales ===")
    latest = get_json(f"{BE}/api/parcel/latest/1")
    if isinstance(latest, dict):
        print(f"  air_temp        = {latest.get('air_temp')} °C")
        print(f"  air_humidity    = {latest.get('air_humidity')} %")
        print(f"  soil_moisture   = {latest.get('soil_moisture')} %")
        print(f"  precipitation   = {latest.get('precipitation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
