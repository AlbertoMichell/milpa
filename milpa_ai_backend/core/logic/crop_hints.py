# milpa_ai_backend/core/logic/crop_hints.py
# ------------------------------------------------------------
# Inferencia de cultivos mencionados en un fragmento y ajuste de score por
# compatibilidad con crop_focus (boost / penalización). Sin columna nueva en BD:
# usa entidades guardadas + taxonomía + extract_entities sobre el texto.
# ------------------------------------------------------------
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from milpa_ai_backend.core.logic.enrichment import extract_entities, load_taxonomy, _norm


def normalize_crop_focus(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return _norm(s)


def _parse_entities_column(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def infer_crop_hints(text: str, entities_json: Optional[str]) -> Tuple[List[str], bool]:
    """
    Devuelve (lista de cultivos canónicos únicos ordenados, multi_crop).
    """
    hints: set = set()
    for e in _parse_entities_column(entities_json):
        t = str(e.get("type") or "").upper()
        if t == "CULTIVO" and e.get("value"):
            hints.add(_norm(str(e["value"])))
    tax = load_taxonomy()
    text_n = _norm(text or "")
    for c in tax.crops:
        if len(c) >= 3 and re.search(rf"\b{re.escape(c)}\b", text_n):
            hints.add(c)
    ents, _, _ = extract_entities(text or "")
    for e in ents:
        if e.type == "CULTIVO" and e.value:
            hints.add(_norm(e.value))
    uniq = sorted(hints)
    return uniq, len(uniq) > 1


_CULTIVO_RULE = re.compile(
    r"\b(si|cuando|para)\s+(el\s+)?cultivo\s+(es\s+)?([a-záéíóúñ]{2,})\b",
    re.IGNORECASE,
)


def adjustment_factor(
    focus_norm: str,
    hints: List[str],
    multi_crop: bool,
    text: str,
    retrieval_scope: str,
) -> Tuple[float, str]:
    """
    Factor multiplicador sobre rrf_score tras recuperación. 1.0 = neutro.
    """
    if not focus_norm:
        return 1.0, "no_focus"

    text_n = _norm(text or "")

    if not hints:
        return 1.0, "neutral_no_hints"

    if focus_norm in hints:
        return (1.25 if retrieval_scope == "crop_boost" else 1.15), "match_crop"

    if multi_crop:
        # Documento que compara/menciona varios cultivos: leve penalización pero sigue útil.
        return 0.80 if retrieval_scope == "crop_strict" else 0.92, "multi_crop_missing_focus"

    # Un solo cultivo explícito distinto al foco.
    # En crop_boost mantenemos un piso de 0.65 para no perder hits buenos cuando
    # NO existe documento del cultivo focal (caso "gusano cogollero del maíz" si
    # la única evidencia disponible es del manual de lechuga).
    other = hints[0]
    factor = 0.65 if retrieval_scope == "crop_boost" else 0.12
    reason = "other_single_crop"

    if _CULTIVO_RULE.search(text_n):
        factor *= 0.70
        reason = "other_single_crop_rule_like"
    if re.search(rf"\bcultivo\b.*\b{re.escape(other)}\b|\b{re.escape(other)}\b.*\bcultivo\b", text_n):
        factor *= 0.85
        reason = "other_single_crop_near_cultivo_keyword"

    return factor, reason


def should_exclude_strict(focus_norm: str, hints: List[str], multi_crop: bool) -> bool:
    """En modo estricto, excluye fragmentos que solo documentan otro cultivo."""
    if not focus_norm or not hints:
        return False
    if multi_crop:
        return False
    if len(hints) == 1 and hints[0] != focus_norm:
        return True
    return False


def synthesis_rank_key(
    frag: Dict[str, Any],
    focus_norm: Optional[str],
) -> Tuple[int, float]:
    """Orden para compose_answer: menor = mejor. Segundo criterio: score descendente."""
    hints = frag.get("crop_hints") or []
    multi = frag.get("crop_multi")
    sc = float(frag.get("score", 0.0))
    if not focus_norm:
        return (0, -sc)
    if focus_norm in hints:
        return (0, -sc)
    if not hints:
        return (1, -sc)
    if multi:
        return (2, -sc)
    return (3, -sc)
