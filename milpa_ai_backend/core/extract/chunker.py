# milpa_ai_backend/core/extract/chunker.py
# Chunking "token-aware" aproximado:
# - Respeta saltos de párrafo y puntos finales.
# - Usa un estimador simple de tokens (~4 chars por token) para no depender de tiktoken.
# - Aplica "overlap" configurable desde settings.CHUNK_OVERLAP (0..1).

from __future__ import annotations
import regex as re
from typing import List, Tuple

def _approx_tokens(s: str) -> int:
    # Aproximación: 1 token ~ 4 caracteres (promedio razonable multilingüe).
    return max(1, (len(s) + 3) // 4)

def split_into_sentences(text: str) -> List[str]:
    """
    Divide el texto en 'oraciones' considerando puntuación y saltos de línea.
    Mantiene delimitadores para no perder contexto.
    """
    text = text.replace("\r\n", "\n")
    # Cortes por líneas en blanco MUY largas para ayudar a segmentar
    blocks = re.split(r"\n{2,}", text)
    sentences: List[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Dividir por signos de final de frase o saltos de línea simples.
        parts = re.split(r"(?<=[\.\!\?\:\;。！？])\s+|\n", block)
        parts = [p.strip() for p in parts if p.strip()]
        if parts:
            sentences.extend(parts)
    return sentences

def chunk_text(
    full_text: str,
    max_tokens: int = 1000,
    overlap_ratio: float = 0.2,
) -> List[str]:
    """
    Crea chunks aproximando el conteo de tokens.
    - max_tokens: tamaño destino por chunk (aprox).
    - overlap_ratio: fracción de solapamiento entre chunks (0..1).
    """
    if not full_text:
        return []

    sentences = split_into_sentences(full_text)
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    for sent in sentences:
        t = _approx_tokens(sent)
        if current and current_tokens + t > max_tokens:
            # Finaliza chunk actual
            chunk = " ".join(current).strip()
            if chunk:
                chunks.append(chunk)
            # Crea "overlap" tomando cola del chunk anterior
            if overlap_ratio > 0 and chunks:
                keep_tokens = int(max_tokens * overlap_ratio)
                tail: List[str] = []
                tally = 0
                for s in reversed(current):
                    ts = _approx_tokens(s)
                    if tally + ts > keep_tokens:
                        break
                    tail.append(s)
                    tally += ts
                current = list(reversed(tail))
                current_tokens = sum(_approx_tokens(s) for s in current)
            else:
                current = []
                current_tokens = 0

        current.append(sent)
        current_tokens += t

    # Último chunk
    last = " ".join(current).strip()
    if last:
        chunks.append(last)

    return chunks

def chunk_pages(
    pages: List[Tuple[int, str]],  # [(page_no, text)]
    max_tokens: int = 1000,
    overlap_ratio: float = 0.2,
) -> List[Tuple[int, int, str]]:
    """
    Chunking sobre un conjunto de páginas; combina respetando páginas contiguas.
    Devuelve lista de tuplas (page_start, page_end, text_chunk).
    """
    results: List[Tuple[int, int, str]] = []
    buffer_text = []
    buffer_pages = []
    tokens = 0

    def flush():
        nonlocal buffer_text, buffer_pages, tokens
        if not buffer_text:
            return
        text = "\n".join(buffer_text).strip()
        for ch in chunk_text(text, max_tokens=max_tokens, overlap_ratio=overlap_ratio):
            results.append((buffer_pages[0], buffer_pages[-1], ch))
        buffer_text = []
        buffer_pages = []
        tokens = 0

    for pno, txt in pages:
        t = max(1, (len(txt) + 3) // 4)
        if tokens + t > max_tokens * 1.5:  # evita chunks gigantes si hay páginas muy densas
            flush()
        buffer_text.append(txt)
        buffer_pages.append(pno)
        tokens += t

    flush()
    return results
