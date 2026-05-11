#!/usr/bin/env python3
"""
E2E mínimo para AgroBot MILPA.

Uso:
  python tools/e2e_agrobot.py --base-url http://127.0.0.1:8000 --user-id 1

Nota:
  Este script no crea cultivos ni sensores. Debe ejecutarse contra una base que
  ya tenga al menos un usuario con cultivos activos y, para el caso multicultivo,
  idealmente dos o más cultivos activos.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class Case:
    name: str
    message: str
    expected_mode: Optional[str] = None
    expected_intent: Optional[str] = None
    require_target: Optional[bool] = None
    require_rag_used: Optional[bool] = None
    forbidden_answer_terms: tuple[str, ...] = ()
    required_answer_terms: tuple[str, ...] = ()


def post_json(url: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"No se pudo conectar: {exc}") from exc


def check_case(base_url: str, user_id: int, case: Case) -> List[str]:
    url = base_url.rstrip("/") + "/api/agrobot/respond"
    payload = {
        "user_id": user_id,
        "username": "E2E AgroBot",
        "message": case.message,
        "source": "e2e",
        "mode": "auto",
    }
    data = post_json(url, payload)
    failures: List[str] = []

    answer = str(data.get("answer") or "").lower()
    rag = data.get("rag") or {}
    target = data.get("target_crop")

    if case.expected_mode and data.get("mode") != case.expected_mode:
        failures.append(f"mode esperado={case.expected_mode!r}, obtenido={data.get('mode')!r}")

    if case.expected_intent and data.get("intent") != case.expected_intent:
        failures.append(f"intent esperado={case.expected_intent!r}, obtenido={data.get('intent')!r}")

    if case.require_target is True and not target:
        failures.append("se esperaba target_crop, pero vino vacío")

    if case.require_target is False and target:
        failures.append(f"no se esperaba target_crop, pero vino {target}")

    if case.require_rag_used is True and not rag.get("used"):
        failures.append("se esperaba rag.used=true")

    if case.require_rag_used is False and rag.get("used"):
        failures.append("se esperaba rag.used=false o rag vacío")

    for term in case.forbidden_answer_terms:
        if term.lower() in answer:
            failures.append(f"answer contiene término prohibido: {term!r}")

    for term in case.required_answer_terms:
        if term.lower() not in answer:
            failures.append(f"answer no contiene término requerido: {term!r}")

    print(f"\n[{case.name}] {case.message!r}")
    print(json.dumps({
        "mode": data.get("mode"),
        "intent": data.get("intent"),
        "target_crop": data.get("target_crop"),
        "warnings": data.get("warnings"),
        "rag_used": bool(rag.get("used")),
        "answer_preview": str(data.get("answer") or "")[:500],
    }, ensure_ascii=False, indent=2))

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()

    cases = [
        Case(
            name="crop-name-contextual",
            message="maíz",
            expected_mode="parcela",
            require_target=True,
            forbidden_answer_terms=("originaria", "historia del maíz"),
            required_answer_terms=("sensores",),
        ),
        Case(
            name="water-balance",
            message="¿cómo estoy de agua?",
            expected_mode="parcela",
            expected_intent="water_balance",
            required_answer_terms=("estado hídrico",),
        ),
        Case(
            name="library-question",
            message="historia del maíz",
            expected_mode="biblioteca",
            expected_intent="library_question",
            require_rag_used=True,
        ),
        Case(
            name="pest-contextual",
            message="plagas en mi maíz",
            expected_mode="parcela",
            expected_intent="pest_or_disease",
            require_target=True,
            require_rag_used=True,
        ),
        Case(
            name="crop-not-active",
            message="tomate",
            required_answer_terms=("no es un cultivo activo",),
        ),
    ]

    all_failures: Dict[str, List[str]] = {}
    for case in cases:
        try:
            failures = check_case(args.base_url, args.user_id, case)
        except Exception as exc:
            failures = [str(exc)]
        if failures:
            all_failures[case.name] = failures

    if all_failures:
        print("\nFALLÓ E2E AgroBot:")
        print(json.dumps(all_failures, ensure_ascii=False, indent=2))
        return 1

    print("\nOK: E2E AgroBot pasó todos los casos configurados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
