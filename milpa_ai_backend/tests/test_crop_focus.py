# milpa_ai_backend/tests/test_crop_focus.py
import pytest

from core.logic.crop_hints import (
    infer_crop_hints,
    adjustment_factor,
    should_exclude_strict,
    normalize_crop_focus,
)
from core.logic.rag_engine import apply_crop_focus_to_hits


def test_infer_crop_hints_from_entities():
    text = "El riego en lechuga debe ser frecuente."
    ent_json = '[{"type":"CULTIVO","value":"lechuga"}]'
    hints, multi = infer_crop_hints(text, ent_json)
    assert "lechuga" in hints
    assert multi is False


def test_adjustment_penalizes_other_single_crop():
    f_lettuce = normalize_crop_focus("Lechuga")
    hints, multi = ["maiz"], False
    fac_boost, _ = adjustment_factor(f_lettuce, hints, multi, "si el cultivo es maiz use riego por goteo", "crop_boost")
    fac_strict, _ = adjustment_factor(f_lettuce, hints, multi, "si el cultivo es maiz use riego por goteo", "crop_strict")
    assert fac_boost < 1.0
    assert fac_strict < fac_boost


def test_strict_excludes_single_other_crop():
    assert should_exclude_strict("lechuga", ["maiz"], False) is True
    assert should_exclude_strict("lechuga", ["lechuga"], False) is False
    assert should_exclude_strict("lechuga", [], False) is False


def test_apply_crop_focus_global_scope_still_annotates():
    hits = [{"fragment_id": "a", "rrf_score": 0.5, "metadata": {}}]
    texts = {"a": "texto sobre maiz"}
    ents = {"a": None}
    out, trace = apply_crop_focus_to_hits(
        hits,
        texts,
        ents,
        crop_focus_norm=None,
        retrieval_scope="global",
        enabled=False,
    )
    assert len(out) == 1
    assert out[0].get("crop_adjust_reason") == "global_scope"


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "riego", "k": 3, "mode": "hybrid"},
        {"query": "riego", "k": 3, "mode": "hybrid", "retrieval_scope": "global"},
    ],
)
def test_query_contract_optional_fields(payload):
    """Contrato API: solo query sigue siendo válido."""
    from api.rag import QueryRequest

    q = QueryRequest(**payload)
    assert q.retrieval_scope == "global"
