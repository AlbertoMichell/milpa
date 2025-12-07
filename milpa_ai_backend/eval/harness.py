"""
Harness de evaluación para el motor RAG.

Métricas soportadas:
- precision@k, recall@k
- MRR (Mean Reciprocal Rank)
- nDCG@k
- entity_coverage (si hay entidades en gold y pred)
- faithfulness (si viene provisto en predicciones)

Formato de entrada (JSONL):
- Golds: {"query": str, "gold_ids": [str], "query_entities": [str]?}
- Preds: {"query": str, "pred_ids": [str], "pred_entities": [[str]]?, "faithfulness": float?}

Nota:
- Los ids pueden ser doc_ids o fragment_ids; el harness no impone semántica.
- entity_coverage se calcula si existen query_entities y pred_entities por posición.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Tuple


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def precision_at_k(pred: List[str], gold: List[str], k: int) -> float:
    if k <= 0:
        return 0.0
    topk = pred[:k]
    if not topk:
        return 0.0
    hit = sum(1 for x in topk if x in gold)
    return hit / float(len(topk))


def recall_at_k(pred: List[str], gold: List[str], k: int) -> float:
    if not gold:
        return 0.0
    topk = set(pred[:k])
    hit = sum(1 for x in gold if x in topk)
    return hit / float(len(gold))


def reciprocal_rank(pred: List[str], gold: List[str]) -> float:
    positions = {pid: i for i, pid in enumerate(pred)}
    rr = 0.0
    for g in gold:
        if g in positions:
            rr = 1.0 / (positions[g] + 1)
            break
    return rr


def dcg_at_k(relevances: List[int], k: int) -> float:
    dcg = 0.0
    for i, rel in enumerate(relevances[:k], start=1):
        # i: 1-based position
        dcg += (2**rel - 1) / math.log2(i + 1)
    return dcg


def ndcg_at_k(pred: List[str], gold: List[str], k: int) -> float:
    # Binario: 1 si está en gold, 0 si no
    relevances = [1 if pid in set(gold) else 0 for pid in pred]
    ideal = sorted(relevances, reverse=True)
    dcg = dcg_at_k(relevances, k)
    idcg = dcg_at_k(ideal, k)
    return (dcg / idcg) if idcg > 0 else 0.0


def entity_coverage(query_entities: List[str], pred_entities_topk: List[List[str]], k: int) -> float:
    """
    Cobertura de entidades de la consulta respecto a las entidades unidas de los top-k predichos.
    query_entities: entidades extraídas de la consulta.
    pred_entities_topk: lista paralela a pred_ids con entidades por ítem.
    """
    if not query_entities or not pred_entities_topk:
        return 0.0
    topk_entities = set()
    for ents in pred_entities_topk[:k]:
        topk_entities.update(ents or [])
    if not topk_entities:
        return 0.0
    hits = sum(1 for e in set(query_entities) if e in topk_entities)
    return hits / float(len(set(query_entities)))


def evaluate(golds: List[Dict[str, Any]], preds: List[Dict[str, Any]], ks: List[int]) -> Dict[str, Any]:
    # Mapear por query
    gold_by_q = {g["query"]: g for g in golds}
    pred_by_q = {p["query"]: p for p in preds}

    agg: Dict[str, List[float]] = defaultdict(list)
    count = 0

    for q, g in gold_by_q.items():
        if q not in pred_by_q:
            continue
        p = pred_by_q[q]
        gold_ids: List[str] = g.get("gold_ids", [])
        pred_ids: List[str] = p.get("pred_ids", [])
        if not isinstance(gold_ids, list) or not isinstance(pred_ids, list):
            continue

        # Métricas por consulta
        for k in ks:
            agg[f"precision@{k}"].append(precision_at_k(pred_ids, gold_ids, k))
            agg[f"recall@{k}"].append(recall_at_k(pred_ids, gold_ids, k))
            agg[f"ndcg@{k}"].append(ndcg_at_k(pred_ids, gold_ids, k))

        agg["mrr"].append(reciprocal_rank(pred_ids, gold_ids))

        # Entity coverage si hay datos
        q_ents = g.get("query_entities") or []
        pred_ents = p.get("pred_entities") or []
        if q_ents and pred_ents:
            for k in ks:
                agg[f"entity_coverage@{k}"].append(entity_coverage(q_ents, pred_ents, k))

        # Faithfulness si está provisto a nivel consulta
        if "faithfulness" in p and isinstance(p["faithfulness"], (int, float)):
            agg["faithfulness"].append(float(p["faithfulness"]))

        count += 1

    # Promediar
    summary: Dict[str, Any] = {"queries_evaluated": count}
    for k, vals in agg.items():
        if vals:
            summary[k] = sum(vals) / len(vals)
    return summary


def print_summary(summary: Dict[str, Any], ks: List[int]) -> None:
    print("================ EVALUACIÓN RAG ================")
    print(f"Consultas evaluadas: {summary.get('queries_evaluated', 0)}")
    for k in ks:
        p = summary.get(f"precision@{k}")
        r = summary.get(f"recall@{k}")
        n = summary.get(f"ndcg@{k}")
        ec = summary.get(f"entity_coverage@{k}")
        if p is not None:
            print(f"precision@{k}: {p:.3f}")
        if r is not None:
            print(f"recall@{k}:    {r:.3f}")
        if n is not None:
            print(f"nDCG@{k}:      {n:.3f}")
        if ec is not None:
            print(f"entity_cov@{k}: {ec:.3f}")
    mrr = summary.get("mrr")
    if mrr is not None:
        print(f"MRR:           {mrr:.3f}")
    faith = summary.get("faithfulness")
    if faith is not None:
        print(f"Faithfulness:  {faith:.3f}")


def parse_ks(s: str) -> List[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    ks = []
    for p in parts:
        try:
            ks.append(int(p))
        except ValueError:
            pass
    return ks or [1, 3, 5]


def main() -> None:
    parser = argparse.ArgumentParser(description="Harness de evaluación RAG")
    parser.add_argument("--gold", required=True, type=Path, help="Ruta a JSONL con golds")
    parser.add_argument("--pred", required=True, type=Path, help="Ruta a JSONL con predicciones")
    parser.add_argument("--ks", default="1,3,5", help="Lista de k separados por coma, p.ej. 1,3,5")
    args = parser.parse_args()

    ks = parse_ks(args.ks)
    golds = load_jsonl(args.gold)
    preds = load_jsonl(args.pred)
    summary = evaluate(golds, preds, ks)
    print_summary(summary, ks)


if __name__ == "__main__":
    main()
