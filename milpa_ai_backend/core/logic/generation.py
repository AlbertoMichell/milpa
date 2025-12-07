# milpa_ai_backend/core/logic/generation.py
# Generación de respuestas local (sin servicios externos)

from typing import List, Dict, Any, Optional
import os


class AnswerGenerator:
    """
    Genera respuestas en lenguaje natural basadas en fragmentos recuperados.
    
    Soporta:
    - Modelos locales (transformers)
    - Fallback: concatenación simple de fragmentos
    """
    
    def __init__(self, mode: str = "concat", model: Optional[str] = None):
        """
        Args:
            mode: "local" | "concat"
            model: Nombre del modelo (ej. "gpt-4", "llama-2-7b")
        """
        self.mode = mode
        self.model = model
        self._client = None
        
        if mode == "local":
            self._init_local_model()
        else:
            self.mode = "concat"
    
    # Modo GPT eliminado: no hay inicialización de clientes externos
    
    def _init_local_model(self):
        """Inicializa modelo local con transformers."""
        try:
            from transformers import pipeline
            self._client = pipeline(
                "text-generation",
                model=self.model or "facebook/opt-350m",
                max_new_tokens=512
            )
            print(f"✓ Generador local inicializado (modelo: {self.model})")
        except ImportError:
            print("Warning: transformers no instalado, usando modo concat")
            self.mode = "concat"
    
    def generate(
        self,
        query: str,
        fragments: List[Dict[str, Any]],
        max_tokens: int = 500,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        Genera respuesta basada en fragmentos.
        
        Args:
            query: Pregunta del usuario
            fragments: Lista de fragmentos con text, score, doc_id
            max_tokens: Máximo de tokens en respuesta
            temperature: Creatividad (0=determinista, 1=creativo)
        
        Returns:
            {
                "answer": str,
                "mode": str,
                "tokens_used": int,
                "citations": List[str]
            }
        """
        if not fragments:
            return {
                "answer": "No se encontró información relevante para responder la pregunta.",
                "mode": "fallback",
                "tokens_used": 0,
                "citations": []
            }
        
        # Construir contexto desde fragmentos
        context_parts = []
        citations = []
        
        for i, frag in enumerate(fragments[:5]):  # Máximo 5 fragmentos
            text = frag.get("text", "")
            doc_id = frag.get("doc_id", "unknown")
            page = frag.get("page_start", "?")
            
            context_parts.append(f"[{i+1}] {text}")
            citations.append(f"[{i+1}] Documento {doc_id[:8]}, página {page}")
        
        context = "\n\n".join(context_parts)
        
        # Generar según modo
        if self.mode == "local":
            return self._generate_local(query, context, citations, max_tokens)
        else:
            return self._generate_concat(query, context, citations)
    
    # Modo GPT eliminado: no hay generación con API externas
    
    def _generate_local(
        self,
        query: str,
        context: str,
        citations: List[str],
        max_tokens: int
    ) -> Dict[str, Any]:
        """Genera respuesta con modelo local."""
        if not self._client:
            return self._generate_concat(query, context, citations)
        
        prompt = f"""Pregunta: {query}

Contexto:
{context}

Respuesta basada en el contexto:"""
        
        try:
            output = self._client(
                prompt,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=0.7
            )
            
            answer = output[0]["generated_text"].replace(prompt, "").strip()
            
            return {
                "answer": answer,
                "mode": "local",
                "tokens_used": len(answer.split()),
                "citations": citations
            }
        
        except Exception as e:
            print(f"Error en generación local: {e}")
            return self._generate_concat(query, context, citations)
    
    def _generate_concat(
        self,
        query: str,
        context: str,
        citations: List[str]
    ) -> Dict[str, Any]:
        """Fallback: concatena fragmentos relevantes."""
        answer = f"""Información encontrada relacionada con: "{query}"

{context}

Fuentes:
""" + "\n".join(citations)
        
        return {
            "answer": answer,
            "mode": "concat",
            "tokens_used": len(answer.split()),
            "citations": citations
        }


# ────────────────────────────────────────────────────────────────
# INSTANCIA GLOBAL
# ────────────────────────────────────────────────────────────────

# Por defecto usa concatenación (sin dependencias externas)
_generator: Optional[AnswerGenerator] = None


def get_generator() -> AnswerGenerator:
    """Obtiene generador singleton."""
    global _generator
    
    if _generator is None:
        # Detectar modo desde env
        mode = os.getenv("GENERATOR_MODE", "concat")
        model = os.getenv("GENERATOR_MODEL")
        
        _generator = AnswerGenerator(mode=mode, model=model)
    
    return _generator
