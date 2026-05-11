# milpa_ai_backend/core/logic/enrichment.py
# ------------------------------------------------------------
# NER y normalización con taxonomías canónicas versionadas.
# - Carga catálogos (CSV/JSON) versionados desde MODELS_DIR/taxonomy/<version>.
# - Normaliza TODO (catálogos y texto de entrada) con:
#     * lowercase
#     * quitar acentos (unidecode)
#   => Comparaciones estables y reproducibles.
# - NER por diccionario SIEMPRE (independiente de spaCy).
#   Si spaCy está instalado y el modelo ES existe, se usa como complemento
#   (EntityRuler añadido a posteriori) para sumar coincidencias.
# - Devuelve entidades normalizadas (type, value=CANÓNICO, original=texto hallado
#   sobre la versión normalizada, offsets sobre ese texto normalizado).
# - Clasificación RECOMENDACION / DATO / RESULTADO sobre texto normalizado.
# - Cobertura de entidades entre consulta y fragmento (canónicos).
# ------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Any
import os
import csv
import re
from pathlib import Path

# Normalización (lower + quitar acentos)
try:
    from unidecode import unidecode
except Exception:
    # Fallback mínimo si no está unidecode (se recomienda instalarlo)
    def unidecode(x: str) -> str:
        return x  # no-op

# spaCy opcional (no es requisito del MVP)
try:
    import spacy
    from spacy.pipeline import EntityRuler
except Exception:
    spacy = None
    EntityRuler = None

# Config opcional (sin dependencia dura)
try:
    from core.config import settings
except Exception:
    class _S:
        MODELS_DIR = "models"
        TAXONOMY_VERSION = "2025.09.10"
    settings = _S()


# -----------------------------
# Utilidades de normalización
# -----------------------------
def _norm(s: str) -> str:
    """Normaliza un string: quita acentos y pasa a minúsculas, y colapsa espacios."""
    if not isinstance(s, str):
        s = str(s)
    s = unidecode(s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -----------------------------
# Estructuras y carga de taxonomías
# -----------------------------
@dataclass
class Taxonomy:
    version: str
    crops: List[str]      # valores canónicos normalizados
    pests: List[str]
    nutrients: List[str]
    phenology: List[str]
    regions: List[str]
    env_params: List[str]  # parámetros ambientales (temperatura, humedad, ph, etc.)
    synonyms: Dict[str, str]  # sinonimo(normalizado) -> canon(normalizado)


def _csv_load_names(path: str) -> List[str]:
    """
    Carga un CSV con columna 'name' y devuelve una lista de valores CANÓNICOS normalizados.
    Si no existe, retorna [].
    """
    if not os.path.exists(path):
        return []
    out: List[str] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Se espera columna: name
        for row in reader:
            name = row.get("name")
            if not name:
                continue
            name = _norm(name)
            if name:
                out.append(name)
    # únicos preservando orden aprox. (por minúsculas/normalizado)
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq


def _json_load_synonyms(path: str) -> Dict[str, str]:
    """
    Carga un JSON tipo {"sinonimo": "canonico", ...}
    y devuelve mapping normalizado sinonimo->canonico.
    """
    import json
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            k_norm = _norm(k)
            v_norm = _norm(v)
            if k_norm and v_norm:
                out[k_norm] = v_norm
    return out


# Cache simple en memoria por versión
_TAX_CACHE: Dict[str, Taxonomy] = {}


def load_taxonomy(version: Optional[str] = None) -> Taxonomy:
    """
    Carga taxonomías canónicas (normalizadas) + sinónimos normalizados.
    """
    ver = version or getattr(settings, "TAXONOMY_VERSION", "2025.09.10")
    if ver in _TAX_CACHE:
        return _TAX_CACHE[ver]

    base = Path(getattr(settings, "MODELS_DIR", "models")) / "taxonomy" / ver
    crops = _csv_load_names(str(base / "crops.csv"))
    pests = _csv_load_names(str(base / "pests.csv"))
    nutrients = _csv_load_names(str(base / "nutrients.csv"))
    phenology = _csv_load_names(str(base / "phenology.csv"))
    regions = _csv_load_names(str(base / "regions.csv"))
    env_params = _csv_load_names(str(base / "env_params.csv"))
    synonyms = _json_load_synonyms(str(base / "synonyms.json"))

    tax = Taxonomy(
        version=ver,
        crops=crops,
        pests=pests,
        nutrients=nutrients,
        phenology=phenology,
        regions=regions,
        env_params=env_params,
        synonyms=synonyms,
    )
    _TAX_CACHE[ver] = tax
    return tax


# -----------------------------
# Sinónimos: normalización previa al NER
# -----------------------------
def normalize_synonyms(text_norm: str, synonyms: Dict[str, str]) -> Tuple[str, Dict[str, str]]:
    """
    Sustituye sinónimos por canónicos sobre el TEXTO YA NORMALIZADO.
    Devuelve (texto_normalizado_reemplazado, {original->canon} aplicados).
    Se usa regex con límites de palabra; se ordena por longitud (desc) para evitar solapes.
    """
    out = text_norm
    applied: Dict[str, str] = {}
    for syn in sorted(synonyms.keys(), key=len, reverse=True):
        can = synonyms[syn]
        # \b sobre texto normalizado (ASCII)
        pattern = re.compile(rf"\b{re.escape(syn)}\b")
        if pattern.search(out):
            out = pattern.sub(can, out)
            applied[syn] = can
    return out, applied


# -----------------------------
# Estructura de entidad
# -----------------------------
@dataclass
class Entity:
    type: str         # "CULTIVO" | "PLAGA" | "NUTRIENTE" | "FENOFASE" | "LUGAR"
    value: str        # canónico normalizado
    original: str     # forma encontrada (sobre texto normalizado)
    start: int        # offsets sobre texto normalizado
    end: int


# -----------------------------
# NER por diccionario (siempre activo)
# -----------------------------
def _dict_ner(text_norm: str, tax: Taxonomy) -> List[Entity]:
    """
    Reconocimiento por diccionario sobre texto NORMALIZADO.
    Devuelve entidades con value canónico (normalizado).
    """
    ents: List[Entity] = []

    def _cap(label: str, items: List[str]):
        for it in items:
            # matching con límites de palabra
            pattern = rf"\b{re.escape(it)}\b"
            for m in re.finditer(pattern, text_norm):
                ents.append(Entity(type=label, value=it, original=m.group(0), start=m.start(), end=m.end()))

    _cap("CULTIVO", tax.crops)
    _cap("PLAGA", tax.pests)
    _cap("NUTRIENTE", tax.nutrients)
    _cap("FENOFASE", tax.phenology)
    _cap("LUGAR", tax.regions)
    _cap("PARAM_AMBIENTAL", tax.env_params)
    return ents


# -----------------------------
# Complemento spaCy (opcional)
# -----------------------------
def _augment_with_spacy(text_norm: str, tax: Taxonomy, base_ents: List[Entity]) -> List[Entity]:
    """
    Si spaCy está disponible, añade un EntityRuler con patrones canónicos normalizados
    y suma coincidencias que no existían ya en base_ents.
    """
    if spacy is None or EntityRuler is None:
        return base_ents

    # Intentar cargar un modelo ES; si no existe, retornar base.
    nlp = None
    for model in ("es_core_news_md", "es_core_news_sm"):
        try:
            nlp = spacy.load(model, disable=["lemmatizer"])
            break
        except Exception:
            nlp = None
    if nlp is None:
        return base_ents

    try:
        ruler = nlp.add_pipe("entity_ruler", name="milpa_entity_ruler", config={"overwrite_ents": False})
    except Exception:
        # Fallback: si falla add_pipe (versiones antiguas), no hacemos nada.
        return base_ents

    patterns = []
    def _phr(label: str, items: List[str]):
        for it in items:
            if it:
                patterns.append({"label": label, "pattern": it})

    _phr("CULTIVO", tax.crops)
    _phr("PLAGA", tax.pests)
    _phr("NUTRIENTE", tax.nutrients)
    _phr("FENOFASE", tax.phenology)
    _phr("LUGAR", tax.regions)
    _phr("PARAM_AMBIENTAL", tax.env_params)

    try:
        ruler.add_patterns(patterns)
        doc = nlp(text_norm)
    except Exception:
        return base_ents

    # Indexar existentes para evitar duplicados exactos (label, span)
    seen = {(e.type, e.start, e.end) for e in base_ents}
    out = list(base_ents)
    for e in doc.ents:
        if e.label_ not in {"CULTIVO", "PLAGA", "NUTRIENTE", "FENOFASE", "LUGAR", "PARAM_AMBIENTAL"}:
            continue
        key = (e.label_, e.start_char, e.end_char)
        if key in seen:
            continue
        out.append(Entity(type=e.label_, value=_norm(e.text), original=e.text, start=e.start_char, end=e.end_char))
        seen.add(key)
    return out


# -----------------------------
# API principal: extracción de entidades
# -----------------------------
def extract_entities(text: str, taxonomy_version: Optional[str] = None) -> Tuple[List[Entity], Dict[str, str], str]:
    """
    Extrae entidades del `text` aplicando:
      1) normalización: lower + quitar acentos
      2) reemplazo de sinónimos -> canónicos
      3) NER por diccionario SIEMPRE
      4) spaCy (opcional) como complemento (EntityRuler)
      5) normalización final del value a canónico
    Retorna: (entities, applied_synonyms, taxonomy_version)
    - Entities incluye offsets sobre el texto normalizado (tras sinónimos).
    """
    tax = load_taxonomy(taxonomy_version)
    text_norm = _norm(text)

    # 1) sinónimos (sobre texto ya normalizado)
    text_norm_syn, applied_syn = normalize_synonyms(text_norm, tax.synonyms)

    # 2) diccionario siempre
    ents = _dict_ner(text_norm_syn, tax)

    # 3) spaCy como plus (silencioso si no está)
    ents = _augment_with_spacy(text_norm_syn, tax, ents)

    # 4) Mapa canónico (incluye inversión de sinónimos)
    canon_map: Dict[str, str] = {}
    for coll in (tax.crops, tax.pests, tax.nutrients, tax.phenology, tax.regions):
        for v in coll:
            canon_map[v] = v
    for syn, can in tax.synonyms.items():
        canon_map[syn] = can

    norm_ents: List[Entity] = []
    for e in ents:
        v = canon_map.get(_norm(e.value), _norm(e.value))
        norm_ents.append(Entity(type=e.type, value=v, original=e.original, start=e.start, end=e.end))

    return norm_ents, applied_syn, tax.version


# -----------------------------
# Clasificación de fragmentos (MVP)
# -----------------------------
_RE_RECO = re.compile(r"\b(se recomienda|aplique|aplicar|dose|dosis|debe|deberia|debería)\b", re.IGNORECASE)
_RE_DATO = re.compile(r"\b(porcentaje|tabla|figura|promedio|media|desviacion|desviación|medicion|medición|datos?)\b", re.IGNORECASE)
_RE_RES  = re.compile(r"\b(resultado|ensayo|rendimiento|incremento|disminucion|disminución|comparado con)\b", re.IGNORECASE)

def classify_fragment(text: str) -> List[str]:
    """
    Etiquetas posibles (no excluyentes): RECOMENDACION, DATO, RESULTADO.
    Trabaja sobre texto normalizado para robustez frente a acentos/sinónimos.
    """
    t = _norm(text)
    labs: List[str] = []
    if _RE_RECO.search(t): labs.append("RECOMENDACION")
    if _RE_DATO.search(t): labs.append("DATO")
    if _RE_RES.search(t):  labs.append("RESULTADO")
    return labs or ["DATO"]  # default neutro


# -----------------------------
# Cobertura de entidades (para RAG)
# -----------------------------
def entity_coverage(query_ents: List[Entity], frag_ents: List[Entity]) -> float:
    """
    Cobertura canónica: |intersección(values)| / |values_query|
    (todo en normalizado-canónico)
    """
    if not query_ents:
        return 0.0
    q = { _norm(e.value) for e in query_ents if e.value }
    f = { _norm(e.value) for e in frag_ents if e.value }
    if not q:
        return 0.0
    inter = len(q & f)
    return round(inter / max(len(q), 1), 4)
