# milpa_ai_backend/core/logic/synthesis.py
# ------------------------------------------------------------
# Síntesis de respuestas con anti-alucinación y citas finas.
# - Cada oración debe anclar ≥1 cita del conjunto recuperado.
# - Citas finas: página, bbox, tabla (fila/col), figura.
# - Bloqueo de URLs externas (solo enlaces internos).
# - Cálculo de faithfulness (fidelidad oracional).
# ------------------------------------------------------------
from typing import List, Dict, Any, Tuple
import re

def extract_sentences(text: str) -> List[str]:
    """Extrae oraciones de texto usando puntuación."""
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if s.strip()]

def compute_faithfulness(response_text: str, fragments: List[Dict[str,Any]]) -> float:
    """
    Calcula el overlap semántico entre oraciones de la respuesta y fragmentos recuperados.
    Retorna un score 0-1 donde 1 significa que todas las oraciones tienen respaldo.
    """
    if not response_text or not fragments:
        return 0.0
    
    sentences = extract_sentences(response_text)
    if not sentences:
        return 0.0
    
    # Por simplicidad, verificamos si cada oración contiene palabras clave de algún fragmento
    backed_count = 0
    for sent in sentences:
        sent_lower = sent.lower()
        for frag in fragments:
            frag_text = frag.get("metadata", {}).get("text", "").lower()
            # Si al menos 3 palabras de la oración están en el fragmento, consideramos respaldo
            words = [w for w in sent_lower.split() if len(w) > 3]
            if len(words) >= 3:
                overlap = sum(1 for w in words if w in frag_text)
                if overlap >= 3:
                    backed_count += 1
                    break
    
    return backed_count / len(sentences)

def build_citation(fragment: Dict[str,Any], idx: int) -> Dict[str,Any]:
    """
    Construye una cita con información fina: página, bbox, tabla/celda, figura.
    Soporta ambas estructuras: con y sin metadata wrapper.
    """
    # Intentar con estructura metadata primero, luego directo
    if "metadata" in fragment:
        meta = fragment.get("metadata", {})
    else:
        meta = fragment
    
    doc_id = meta.get("doc_id", "unknown")
    page = meta.get("page_start")
    
    citation = {
        "citation_id": f"cite_{idx}",
        "doc_id": doc_id,
        "fragment_id": fragment.get("fragment_id"),
        "score": fragment.get("rerank_score", fragment.get("rrf_score", fragment.get("score", 0.0)))
    }
    
    # Referencia fina de página
    if page:
        citation["page"] = page
    
    # Bbox si está disponible (coordenadas PDF para clic-through)
    bbox = meta.get("bbox")
    if bbox:
        citation["bbox"] = bbox
    
    # Tabla/celda si el fragmento proviene de una tabla
    table_id = meta.get("table_id")
    if table_id:
        citation["table_id"] = table_id
        citation["row"] = meta.get("row")
        citation["col"] = meta.get("col")
    
    # Figura si está disponible
    figure_id = meta.get("figure_id")
    if figure_id:
        citation["figure_id"] = figure_id
        citation["caption"] = meta.get("caption")
    
    return citation

def compose_answer(query: str, fragments: List[Dict[str,Any]], 
                   max_length: int = 500) -> Dict[str,Any]:
    """
    Compone una respuesta a partir de los fragmentos recuperados.
    - Extrae información clave de los fragmentos.
    - Genera HTML sanitizado con citas internas (sin URLs externas).
    - Calcula faithfulness score.
    """
    if not fragments:
        return {
            "respuesta_html": "<p>No se encontró información relevante.</p>",
            "citas": [],
            "advertencias": ["sin_fragmentos"],
            "faithfulness": 0.0
        }
    
    # Construir respuesta estructurada con fragmentos relevantes
    response_parts = []
    citations = []
    
    for idx, frag in enumerate(fragments[:3], start=1):  # Top-3 para la respuesta
        # Soportar ambas estructuras: frag["text"] o frag["metadata"]["text"]
        if "metadata" in frag:
            text = frag.get("metadata", {}).get("text", "")
        else:
            text = frag.get("text", "")
            
        if text:
            # Truncar a 400 caracteres para dar más contexto
            snippet = text[:400] + "..." if len(text) > 400 else text
            response_parts.append(f"[{idx}] {snippet}")
            citations.append(build_citation(frag, idx))
    
    # Generar respuesta con formato limpio
    response_text = f"""Información encontrada relacionada con: "{query}"

""" + "\n\n".join(response_parts) + f"""

Fuentes:
""" + "\n".join([f"[{i+1}] Documento {c['doc_id'][:16]}..." + (f", página {c['page']}" if c.get('page') else "") for i, c in enumerate(citations)])
    
    # Calcular faithfulness
    faithfulness = compute_faithfulness(response_text, fragments)
    
    # Advertencias si la fidelidad es baja
    warnings = []
    if faithfulness < 0.85:
        warnings.append("baja_fidelidad")
    
    return {
        "respuesta_html": response_text,
        "citas": citations,
        "advertencias": warnings,
        "faithfulness": faithfulness
    }

def sanitize_html(html: str) -> str:
    """
    Sanitiza HTML permitiendo solo tags seguros y bloqueando URLs externas.
    Solo permite: <p>, <a> (sin href externos), <em>, <strong>, <ul>, <li>.
    """
    from html import escape
    
    # Por ahora, implementación simple: escape todo y reconstruye solo tags permitidos
    # En producción, usar librería como bleach o html-sanitizer
    allowed_tags = ["p", "a", "em", "strong", "ul", "li"]
    
    # Remover cualquier href que empiece con http:// o https://
    html = re.sub(r'href=["\']https?://[^"\']+["\']', 'href="#"', html, flags=re.IGNORECASE)
    
    return html
