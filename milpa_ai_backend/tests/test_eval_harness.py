import json
from pathlib import Path

from eval.harness import evaluate


def test_eval_harness_basic(tmp_path: Path):
    gold = [
        {"query": "fertilizacion maiz macollaje", "gold_ids": ["f1", "f2"], "query_entities": ["maiz", "n"]},
        {"query": "control gusano cogollero", "gold_ids": ["f3"], "query_entities": ["plaga:gusano_cogollero"]},
    ]
    pred = [
        {"query": "fertilizacion maiz macollaje", "pred_ids": ["f1", "f9", "f2"], "pred_entities": [["maiz"], ["soja"], ["n"]], "faithfulness": 1.0},
        {"query": "control gusano cogollero", "pred_ids": ["x", "f3"], "pred_entities": [["plaga:oruga"], ["plaga:gusano_cogollero"]]},
    ]

    ks = [1, 3]
    summary = evaluate(gold, pred, ks)

    assert summary["queries_evaluated"] == 2
    # precision@1: (1 + 0) / 2 = 0.5
    assert 0.45 <= summary["precision@1"] <= 0.55
    # recall@1: (1/2 + 0/1) / 2 = 0.25
    assert 0.20 <= summary["recall@1"] <= 0.30
    # nDCG debe ser > 0.6 dado f1 en posición 1 y f2 en 3
    assert summary["ndcg@3"] > 0.6
    # MRR > 0.5 (f1 pos 1; f3 pos 2)
    assert summary["mrr"] > 0.5
    # entity coverage calculable y > 0
    assert summary["entity_coverage@3"] > 0
    # faithfulness: solo se promedia sobre consultas que lo proveen → 1.0
    assert 0.95 <= summary["faithfulness"] <= 1.0
