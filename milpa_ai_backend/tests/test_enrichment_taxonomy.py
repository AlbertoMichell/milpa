# milpa_ai_backend/tests/test_enrichment_taxonomy.py
# ------------------------------------------------------------
# Pruebas de NER + taxonomías + cobertura de entidades.
# ------------------------------------------------------------
import pytest
from core.logic.enrichment import extract_entities, entity_coverage, classify_fragment

def test_extract_entities_and_synonyms():
    text = "Se recomienda fertilización con N en maíz durante macollaje en Puebla."
    ents, syn_map, tax_ver = extract_entities(text)
    values = { (e.type, e.value.lower()) for e in ents }

    # Sinónimos: "maíz" -> "maiz"
    assert ("CULTIVO","maiz") in values
    # Detección de N
    assert ("NUTRIENTE","n") in values or ("NUTRIENTE","N") in { (t,v) for t,v in values }
    # Fenofase y lugar
    assert ("FENOFASE","macollaje") in values
    assert ("LUGAR","puebla") in values
    # Versión de taxonomía presente
    assert isinstance(tax_ver, str) and len(tax_ver) > 0

def test_entity_coverage_basic():
    q_ents, _, _ = extract_entities("dosis de N en maiz durante macollaje")
    f_ents, _, _ = extract_entities("Se recomienda N en maiz en macollaje; datos de Puebla.")
    cov = entity_coverage(q_ents, f_ents)
    assert cov >= 0.66  # 2/3 o mejor

def test_classify_fragment_labels():
    assert "RECOMENDACION" in classify_fragment("Se recomienda aplicar fertilización.")
    assert "DATO" in classify_fragment("Tabla 2: promedio de rendimiento.")
    assert "RESULTADO" in classify_fragment("El rendimiento aumentó comparado con el control.")
