# milpa_ai_backend/tests/test_rerank_synthesis.py
# ------------------------------------------------------------
# Pruebas para SPRINT 9–11:
# - Reranking multi-factor (sim, frescura, autoridad, entidades)
# - Síntesis con citas finas (página, bbox, tabla/celda, figura)
# - Faithfulness score (fidelidad oracional)
# - Sanitización HTML (sin URLs externas)
# ------------------------------------------------------------
import pytest
from core.logic.rag_engine import rerank_top_n
from core.logic.synthesis import compose_answer, compute_faithfulness, sanitize_html, build_citation

def test_rerank_with_factors(sample_fragments):
    """
    Verifica que el reranking aplique pesos correctamente y reordene por score combinado.
    """
    # Simular hits con metadata variada
    hits = [
        {
            "fragment_id": "f1",
            "rrf_score": 0.5,
            "metadata": {
                "text": "Fertilización con N en maiz durante macollaje.",
                "doc_id": "doc_maiz_1",
                "source": "INIFAP Manual 2023",
                "created_at": "2023-01-15T10:00:00",
                "page_start": 12
            }
        },
        {
            "fragment_id": "f2",
            "rrf_score": 0.45,
            "metadata": {
                "text": "Control de gusano cogollero en maiz.",
                "doc_id": "doc_maiz_2",
                "source": "Autor Desconocido",
                "created_at": "2020-03-10T08:00:00",
                "page_start": 5
            }
        },
        {
            "fragment_id": "f3",
            "rrf_score": 0.48,
            "metadata": {
                "text": "Rendimiento promedio en maiz bajo riego.",
                "doc_id": "doc_maiz_3",
                "source": "FAO Report 2024",
                "created_at": "2024-06-01T12:00:00",
                "page_start": 8
            }
        }
    ]
    
    query = "fertilización N maiz macollaje"
    reranked = rerank_top_n(hits, query, topn=10)
    
    # Verificaciones
    assert len(reranked) == 3
    assert all("rerank_score" in h for h in reranked)
    assert all("factors" in h for h in reranked)
    
    # El primer hit debería tener score alto por:
    # - Alta similitud base (rrf_score)
    # - Fuente oficial (INIFAP)
    # - Cobertura de entidades (contiene "N", "maiz", "macollaje")
    top_hit = reranked[0]
    assert top_hit["fragment_id"] in ["f1", "f3"]  # f1 o f3 deberían estar arriba
    
    # Verificar que los factores se calcularon
    factors = top_hit["factors"]
    assert "sim" in factors
    assert "fresh" in factors
    assert "auth" in factors
    assert "entity" in factors
    
    print(f"✓ Reranking aplicado correctamente. Top hit: {top_hit['fragment_id']} con score {top_hit['rerank_score']:.3f}")

def test_synthesis_with_citations(sample_fragments):
    """
    Verifica que la síntesis genere respuestas con citas finas (página, bbox, tabla/celda).
    """
    fragments = [
        {
            "fragment_id": "f1",
            "rrf_score": 0.85,
            "metadata": {
                "text": "Se recomienda aplicar 120 kg/ha de N en maiz durante macollaje para maximizar rendimiento.",
                "doc_id": "doc_inifap_01",
                "page_start": 15,
                "bbox": [100, 200, 400, 250],
                "source": "INIFAP"
            }
        },
        {
            "fragment_id": "f2",
            "rrf_score": 0.78,
            "metadata": {
                "text": "Tabla 3: Dosis de N por cultivo y etapa fenológica",
                "doc_id": "doc_inifap_01",
                "page_start": 16,
                "table_id": "table_3",
                "row": 5,
                "col": 2
            }
        }
    ]
    
    query = "dosis de N para maiz en macollaje"
    response = compose_answer(query, fragments)
    
    # Verificaciones
    assert "respuesta_html" in response
    assert "citas" in response
    assert "faithfulness" in response
    
    # Debe haber al menos 2 citas
    assert len(response["citas"]) >= 2
    
    # Verificar estructura de citas
    cite1 = response["citas"][0]
    assert "doc_id" in cite1
    assert "fragment_id" in cite1
    assert "score" in cite1
    
    # La primera cita debe tener página y bbox
    assert "page" in cite1
    assert "bbox" in cite1
    
    # La segunda cita debe tener tabla/celda
    cite2 = response["citas"][1]
    assert "table_id" in cite2
    assert "row" in cite2
    assert "col" in cite2
    
    # Verificar que no hay URLs externas en el HTML
    html = response["respuesta_html"]
    assert "http://" not in html
    assert "https://" not in html
    assert "data-cite=" in html  # Debe tener enlaces internos
    
    print(f"✓ Síntesis generada con {len(response['citas'])} citas finas")
    print(f"✓ Faithfulness score: {response['faithfulness']:.2f}")

def test_faithfulness_calculation():
    """
    Verifica que el cálculo de faithfulness detecte correctamente el respaldo oracional.
    """
    # Respuesta bien respaldada
    response_good = "La fertilización con N en maiz durante macollaje mejora el rendimiento."
    fragments_good = [
        {"metadata": {"text": "Se recomienda fertilización con N en maiz durante la etapa de macollaje para maximizar el rendimiento final del cultivo."}}
    ]
    
    faithfulness_good = compute_faithfulness(response_good, fragments_good)
    assert faithfulness_good > 0.5, f"Faithfulness bajo cuando debería ser alto: {faithfulness_good}"
    
    # Respuesta mal respaldada (información no presente en fragmentos)
    response_bad = "El tomate requiere riego cada 6 horas en clima tropical."
    fragments_bad = [
        {"metadata": {"text": "La fertilización con N en maiz durante macollaje mejora rendimiento."}}
    ]
    
    faithfulness_bad = compute_faithfulness(response_bad, fragments_bad)
    assert faithfulness_bad < 0.5, f"Faithfulness alto cuando debería ser bajo: {faithfulness_bad}"
    
    print(f"✓ Faithfulness bueno: {faithfulness_good:.2f}")
    print(f"✓ Faithfulness malo: {faithfulness_bad:.2f}")

def test_sanitize_html_blocks_external_urls():
    """
    Verifica que la sanitización bloquee URLs externas pero permita enlaces internos.
    """
    # HTML con URL externa (debe bloquearse)
    html_external = '<p>Ver más en <a href="https://ejemplo.com">este sitio</a></p>'
    sanitized = sanitize_html(html_external)
    assert "https://ejemplo.com" not in sanitized
    assert "href=\"#\"" in sanitized
    
    # HTML con enlace interno (debe permitirse)
    html_internal = '<p>Ver cita <a data-cite="cite_1">[1]</a></p>'
    sanitized_internal = sanitize_html(html_internal)
    assert "data-cite" in sanitized_internal
    
    print("✓ Sanitización HTML funcionando correctamente")

def test_build_citation_with_fine_refs():
    """
    Verifica que build_citation genere referencias finas correctamente.
    """
    # Fragmento con bbox
    frag_bbox = {
        "fragment_id": "f1",
        "rerank_score": 0.9,
        "metadata": {
            "doc_id": "doc_test",
            "page_start": 10,
            "bbox": [50, 100, 300, 150]
        }
    }
    
    citation = build_citation(frag_bbox, 1)
    assert citation["page"] == 10
    assert citation["bbox"] == [50, 100, 300, 150]
    assert citation["citation_id"] == "cite_1"
    
    # Fragmento de tabla
    frag_table = {
        "fragment_id": "f2",
        "rrf_score": 0.85,
        "metadata": {
            "doc_id": "doc_test",
            "page_start": 12,
            "table_id": "table_5",
            "row": 3,
            "col": 4
        }
    }
    
    citation_table = build_citation(frag_table, 2)
    assert citation_table["table_id"] == "table_5"
    assert citation_table["row"] == 3
    assert citation_table["col"] == 4
    
    print("✓ Citas finas (bbox, tabla/celda) generadas correctamente")
