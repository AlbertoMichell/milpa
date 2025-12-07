# milpa_ai_backend/core/logic/translation.py
# ------------------------------------------------------------
# Detección de idioma y traducción local con:
#   - Glosario canónico versionado (do_not_translate).
#   - Memoria de traducción (TM) por context_hash (si aplica).
#   - Métricas de consistencia (Consistency Score).
# Dependencias opcionales: langdetect/fasttext, transformers.
# Si faltan, el módulo sigue funcionando con fallbacks (devuelve texto original).
# ------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import hashlib
import json
import os
import re

# Opcionales
try:
    from langdetect import detect  # simple; en prod puedes preferir fastText
except Exception:
    detect = None

try:
    from transformers import pipeline
except Exception:
    pipeline = None


@dataclass
class Term:
    src: str
    es: str
    domain: str
    dnt: bool  # do_not_translate


def load_glossary(base_dir: str, version: str) -> List[Term]:
    """
    Carga CSV de glosario versionado (term_src,term_es,domain,do_not_translate,version).
    """
    import csv
    path = os.path.join(base_dir, version, "glossary.csv")
    terms: List[Term] = []
    if not os.path.exists(path):
        return terms
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            terms.append(
                Term(
                    src=row["term_src"],
                    es=row["term_es"],
                    domain=row.get("domain", ""),
                    dnt=row.get("do_not_translate", "false").lower() in ("1", "true", "yes"),
                )
            )
    return terms


def load_tm(base_dir: str, version: str) -> Dict[Tuple[str, str], str]:
    """
    Carga TM versionada en JSONL con campos: src, tgt, context_hash, version.
    Index: (src, context_hash) -> tgt
    """
    path = os.path.join(base_dir, version, "translation_memory.jsonl")
    mapping: Dict[Tuple[str, str], str] = {}
    if not os.path.exists(path):
        return mapping
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                mapping[(obj["src"], obj["context_hash"])] = obj["tgt"]
            except Exception:
                continue
    return mapping


def _context_hash(text: str, window: int = 200) -> str:
    """
    Hash de contexto simple: primeros N caracteres normalizados.
    (Puedes mejorarlo a ventanas deslizantes si lo necesitas.)
    """
    key = text[:window].strip().lower()
    return hashlib.sha1(key.encode()).hexdigest()


def enforce_do_not_translate(text: str, terms: List[Term]) -> Tuple[str, Dict[str, str]]:
    """
    Enmascara términos DNT antes de traducir y devuelve:
      - texto con placeholders
      - mapping placeholder -> término original
    """
    mapping: Dict[str, str] = {}
    protected = text
    for i, t in enumerate(terms):
        if not t.dnt:
            continue
        pattern = re.escape(t.src)
        placeholder = f"⟦DNT_{i}⟧"
        if re.search(pattern, protected, flags=re.IGNORECASE):
            protected = re.sub(pattern, placeholder, protected, flags=re.IGNORECASE)
            mapping[placeholder] = t.src
    return protected, mapping


def restore_do_not_translate(text: str, mapping: Dict[str, str]) -> str:
    restored = text
    for ph, orig in mapping.items():
        restored = restored.replace(ph, orig)
    return restored


def _apply_glossary_post(text: str, terms: List[Term]) -> str:
    """
    Post-procesado con glosario: reemplaza term_src -> term_es si NO es DNT.
    (Se asume texto destino en español.)
    """
    out = text
    for t in terms:
        if t.dnt:
            continue
        # Reemplazo insensible a mayúsculas, usando límites suaves
        pattern = re.compile(rf"\b{re.escape(t.src)}\b", flags=re.IGNORECASE)
        out = pattern.sub(t.es, out)
    return out


def compute_consistency_score(text: str, terms: List[Term]) -> float:
    """
    Porcentaje de términos no-DNT del glosario que aparecen normalizados en el texto traducido.
    """
    check_terms = [t for t in terms if not t.dnt]
    if not check_terms:
        return 1.0
    hits = 0
    for t in check_terms:
        if re.search(rf"\b{re.escape(t.es)}\b", text, flags=re.IGNORECASE):
            hits += 1
    return round(hits / len(check_terms), 4)


def detect_lang(text: str) -> Tuple[str, float]:
    """
    Detección de idioma (simple).
    Si langdetect no está disponible, devolvemos ('es', 0.5) como fallback.
    """
    if not text or len(text.strip()) < 3:
        return "es", 1.0
    if detect is None:
        return "es", 0.5
    try:
        code = detect(text)
        # langdetect no retorna confianza; damos constante si no integra fastText
        return code, 0.99 if code else 0.5
    except Exception:
        return "es", 0.5


def translate_to_es(
    text: str,
    glossary: List[Term],
    tm: Dict[Tuple[str, str], str],
    model_name: Optional[str] = None,
) -> Tuple[str, Dict[str, float]]:
    """
    Traduce texto a español con TM y glosario. Retorna:
      - texto_en_es
      - métricas: {"consistency":..., "tm_hit":0/1}
    """
    if not text.strip():
        return text, {"consistency": 1.0, "tm_hit": 0.0}

    # TM exacta por contexto
    ch = _context_hash(text)
    if (text, ch) in tm:
        out = tm[(text, ch)]
        out = _apply_glossary_post(out, glossary)
        return out, {"consistency": compute_consistency_score(out, glossary), "tm_hit": 1.0}

    # Enmascarar DNT
    protected, mapping = enforce_do_not_translate(text, glossary)

    # Traducción
    if pipeline is None:
        # Fallback: sin transformers → devolvemos el mismo texto
        translated = protected
    else:
        # Modelo: si no se indica, intentamos uno multi-idioma a ES (ajústalo si ya tienes local)
        model = model_name or "Helsinki-NLP/opus-mt-mul-es"
        try:
            trans = pipeline("translation", model=model)
            translated = trans(protected, max_length=2048)[0]["translation_text"]
        except Exception:
            translated = protected  # fallback silencioso

    # Restaurar DNT y post-proceso con glosario
    translated = restore_do_not_translate(translated, mapping)
    translated = _apply_glossary_post(translated, glossary)

    return translated, {"consistency": compute_consistency_score(translated, glossary), "tm_hit": 0.0}
