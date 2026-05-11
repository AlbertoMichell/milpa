from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


BAD_MARKERS = [
    "eres el componente documental",
    "no debes desplazar",
    "pregunta del agricultor",
    "devuelve solo manejo técnico",
    "devuelve solo manejo tecnico",
    "parámetros agronómicos relevantes para «recomendaciones",
    "parametros agronomicos relevantes para «recomendaciones",
]


def post_json(url: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def assert_no_prompt_leak(answer: str) -> Optional[str]:
    normalized = answer.lower()
    for marker in BAD_MARKERS:
        if marker.lower() in normalized:
            return f"fuga de prompt o texto interno: {marker}"
    return None


def run_case(base_url: str, user_id: int, message: str, expected_mode: Optional[str] = None) -> List[str]:
    payload = {
        "user_id": user_id,
        "username": "E2E",
        "message": message,
        "source": "e2e_agrobot",
        "mode": "auto",
    }
    response = post_json(f"{base_url.rstrip('/')}/api/agrobot/respond", payload)
    answer = str(response.get("answer") or "")
    errors: List[str] = []

    if not answer.strip():
        errors.append("respuesta vacía")

    leak = assert_no_prompt_leak(answer)
    if leak:
        errors.append(leak)

    if expected_mode and response.get("mode") != expected_mode:
        errors.append(f"modo esperado {expected_mode}, recibido {response.get('mode')}")

    if message.lower().strip() in {"maíz", "maiz"}:
        if "historia" in answer.lower() or "originari" in answer.lower():
            errors.append("la consulta de estado de cultivo devolvió historia/origen")
        if "sensores" not in answer.lower() and "humedad" not in answer.lower():
            errors.append("la consulta de cultivo no incluyó sensores/humedad")

    if "agua" in message.lower() and "estado hídrico" not in answer.lower():
        errors.append("la consulta de agua no devolvió estado hídrico")

    if "historia" in message.lower():
        if response.get("mode") != "biblioteca":
            errors.append("consulta histórica no entró en modo biblioteca")
        if not answer.strip():
            errors.append("consulta histórica sin respuesta ni insuficiencia")

    print("\n===", message, "===")
    print("mode:", response.get("mode"), "intent:", response.get("intent"), "warnings:", response.get("warnings"))
    print(answer[:1000])
    if errors:
        print("ERRORES:")
        for err in errors:
            print("-", err)
    else:
        print("OK")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Pruebas E2E básicas para AgroBot MILPA")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    cases = [
        ("maíz", "parcela"),
        ("¿cómo estoy de agua?", "parcela"),
        ("historia del maíz", "biblioteca"),
        ("plagas en mi maíz", "parcela"),
        ("tomate", None),
    ]

    all_errors: List[str] = []
    for message, expected_mode in cases:
        try:
            errors = run_case(args.base_url, args.user_id, message, expected_mode)
            all_errors.extend([f"{message}: {err}" for err in errors])
        except Exception as exc:
            all_errors.append(f"{message}: excepción {exc}")
            print("\n===", message, "===")
            print("EXCEPCIÓN:", exc)

    if all_errors:
        print("\nRESULTADO: FALLÓ")
        for err in all_errors:
            print("-", err)
        return 1

    print("\nRESULTADO: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
