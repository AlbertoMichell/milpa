"""Auditoría RAG: 10 simples + 10 compuestas.

Ejecuta consultas contra http://127.0.0.1:8000/api/query y guarda un reporte JSON
con los hallazgos clave: nº de fragmentos, doc_ids únicos, encabezado de la
respuesta, lista de títulos. Imprime una tabla ASCII con los campos relevantes.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List

BACKEND = "http://127.0.0.1:8000"

SIMPLE = [
    "Maíz",
    "Lechuga",
    "Frijol",
    "Calabaza",
    "Pepino",
    "Tomate",
    "Riego",
    "Fertilización",
    "Plagas",
    "Suelo",
]

COMPOUND = [
    "Temperatura ideal para la lechuga",
    "pH óptimo del suelo para maíz",
    "Dosis de nitrógeno por hectárea en maíz",
    "¿Cómo se controla el gusano cogollero del maíz?",
    "¿Cuándo regar la lechuga en clima cálido?",
    "Ciclo de cultivo del frijol en sistema milpa",
    "Distancia de siembra recomendada para calabaza",
    "¿Qué humedad de suelo necesita el pepino?",
    "Variedades de tomate resistentes a sequía",
    "Manejo integrado de plagas en lechuga",
]


def call(query: str) -> Dict[str, Any]:
    body = json.dumps({"query": query, "k": 5, "mode": "hybrid"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND}/api/query",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}"}
    except Exception as e:
        return {"_error": str(e)}
    data["_elapsed_ms"] = int((time.time() - t0) * 1000)
    return data


def summarize(query: str, kind: str, res: Dict[str, Any]) -> Dict[str, Any]:
    if "_error" in res:
        return {
            "kind": kind, "query": query, "error": res["_error"],
            "elapsed_ms": 0, "n_fragments": 0, "unique_doc_ids": 0,
            "answer_first_240": "", "titles": [], "answer_mode": "error",
            "insufficient": True, "auto_focus": None, "crop_focus": None,
        }
    frags = res.get("fragments") or []
    titles = [f.get("doc_title") or f.get("doc_id", "")[:8] for f in frags]
    doc_ids = {f.get("doc_id") for f in frags if f.get("doc_id")}
    answer = (res.get("answer") or "").replace("\n", " ").strip()
    if len(answer) > 280:
        answer = answer[:280] + "…"
    crop_trace = res.get("crop_trace") or {}
    return {
        "kind": kind,
        "query": query,
        "elapsed_ms": res.get("_elapsed_ms"),
        "answer_mode": res.get("answer_mode"),
        "insufficient": bool(res.get("insufficient_evidence")),
        "n_fragments": len(frags),
        "unique_doc_ids": len(doc_ids),
        "titles": titles,
        "auto_focus": crop_trace.get("auto_focus_from_query"),
        "crop_focus": crop_trace.get("crop_focus") or crop_trace.get("focus"),
        "scope": crop_trace.get("retrieval_scope"),
        "answer_first_240": answer,
    }


def main() -> int:
    rows: List[Dict[str, Any]] = []
    for q in SIMPLE:
        rows.append(summarize(q, "simple", call(q)))
    for q in COMPOUND:
        rows.append(summarize(q, "compound", call(q)))

    with open("tools/rag_audit_report.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    headers = ["kind", "query", "ms", "frags", "docs", "focus", "auto"]
    widths = [9, 50, 5, 6, 5, 12, 5]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        cells = [
            r["kind"],
            (r["query"] or "")[:50],
            str(r.get("elapsed_ms") or ""),
            str(r["n_fragments"]),
            str(r["unique_doc_ids"]),
            (r.get("crop_focus") or "-")[:12],
            "Y" if r.get("auto_focus") else "-",
        ]
        print("  ".join(c.ljust(w) for c, w in zip(cells, widths)))

    print("\n=== respuestas (primer extracto) ===")
    for r in rows:
        print(f"\n[{r['kind']}] {r['query']}  →  ({r['n_fragments']} frags / {r['unique_doc_ids']} docs)")
        print(f"  focus={r.get('crop_focus')} auto={r.get('auto_focus')}")
        print(f"  {r['answer_first_240']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
