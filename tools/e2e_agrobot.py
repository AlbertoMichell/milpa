#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


TESTS = [
    ("maíz", {"mode": "parcela", "not_contains": ["originaria", "GUÍA COMPLETA", "Eres el componente"]}),
    ("¿cómo estoy de agua?", {"mode": "parcela", "contains": ["Estado hídrico"]}),
    ("Temperatura", {"mode": "parcela", "contains_any": ["Temperatura actual", "Sensores actuales", "temperatura"]}),
    ("Viento", {"mode": "parcela", "contains_any": ["Viento actual", "viento"]}),
    ("Clima", {"mode": "parcela", "contains_any": ["Condición climática", "temperatura"]}),
    ("fsjshjsjd", {"intent": "garbage", "contains": ["No entendí"]}),
    ("historia del maíz", {"mode": "biblioteca", "not_contains": ["Eres el componente", "GUÍA COMPLETA"]}),
    ("plagas", {"mode": "parcela", "contains_any": ["cultivo específico", "Cultivos activos"]}),
]


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_result(question: str, resp: dict, expected: dict) -> list[str]:
    errors: list[str] = []
    answer = str(resp.get("answer") or "")
    if expected.get("mode") and resp.get("mode") != expected["mode"]:
        errors.append(f"mode esperado {expected['mode']} != {resp.get('mode')}")
    if expected.get("intent") and resp.get("intent") != expected["intent"]:
        errors.append(f"intent esperado {expected['intent']} != {resp.get('intent')}")
    for term in expected.get("contains", []):
        if term.lower() not in answer.lower():
            errors.append(f"no contiene {term!r}")
    if expected.get("contains_any"):
        if not any(term.lower() in answer.lower() for term in expected["contains_any"]):
            errors.append(f"no contiene ninguno de {expected['contains_any']!r}")
    for term in expected.get("not_contains", []):
        if term.lower() in answer.lower():
            errors.append(f"contiene texto prohibido {term!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Pruebas E2E rápidas para AgroBot.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()
    url = args.base_url.rstrip("/") + "/api/agrobot/respond"
    failures = 0
    for question, expected in TESTS:
        payload = {"user_id": args.user_id, "message": question, "source": "e2e", "mode": "auto"}
        try:
            resp = post_json(url, payload)
        except Exception as exc:
            failures += 1
            print(f"[ERROR] {question!r}: {exc}")
            continue
        errors = check_result(question, resp, expected)
        status = "OK" if not errors else "FAIL"
        if errors:
            failures += 1
        print(f"[{status}] {question!r} -> mode={resp.get('mode')} intent={resp.get('intent')}")
        print((resp.get("answer") or "").split("\n")[0][:180])
        if errors:
            print("  Errores:", "; ".join(errors))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
