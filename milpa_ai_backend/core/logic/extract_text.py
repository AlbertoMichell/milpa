"""Extracción enriquecida para archivos TXT y Markdown.

Reglas:
  - Detecta saltos de página explícitos:
      * ``\\f`` (form feed, estándar de PDF→texto via pdftotext).
      * Línea con solo ``---`` (separador frontmatter / Markdown).
      * Línea con solo ``\\x0c``.
  - Si no hay marcadores, pagina cada ~500 palabras (alineado con DOCX).
  - Markdown: si hay encabezados ``#``, ``##``, ``###``, los anota como
    headings (un fragmento separado) y se promueven a inicio de página cuando
    son ``# ...`` (h1) — convención común para apuntes/manuales.
  - Devuelve texto por página y bloques estructurados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# Heurísticas de paginación
_PAGE_BREAK = re.compile(r"\f|\x0c|^\s*-{3,}\s*$", re.MULTILINE)
_DEFAULT_WORDS_PER_PAGE = 500


@dataclass
class TextBlock:
    kind: str  # "heading" | "paragraph" | "list" | "code" | "page_break"
    page: int
    text: str
    level: int = 0


@dataclass
class TextExtraction:
    blocks: List[TextBlock] = field(default_factory=list)
    n_pages: int = 1
    raw_text: str = ""

    def texts_per_page(self) -> dict[int, str]:
        out: dict[int, list[str]] = {}
        for b in self.blocks:
            if b.kind == "page_break" or not b.text.strip():
                continue
            out.setdefault(b.page, []).append(b.text)
        return {p: "\n\n".join(v) for p, v in out.items()}


def _read_text_file(path: str) -> str:
    """Lee con detección de encoding sencilla (utf-8 → utf-8-sig → latin-1)."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return ""


_RE_HEADING_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_RE_LIST_MD = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)(.+)$")
_RE_CODE_FENCE = re.compile(r"^\s*```")


def _is_markdown(path: str) -> bool:
    p = path.lower()
    return p.endswith(".md") or p.endswith(".markdown")


def extract_text(
    path: str,
    words_per_page: int = _DEFAULT_WORDS_PER_PAGE,
) -> TextExtraction:
    """Lee un .txt o .md y produce bloques estructurados con paginación.

    El callsite (endpoint) usa ``texts_per_page`` para indexar fragments por
    página real, lo que mejora la cita en RAG (antes todo caía en page=1).
    """
    raw = _read_text_file(path)
    out = TextExtraction(raw_text=raw)

    if not raw.strip():
        return out

    # 1. Particionar por marcadores explícitos de salto de página.
    pages_raw = _PAGE_BREAK.split(raw)
    if len(pages_raw) == 1:
        # Sin marcadores: paginar cada N palabras manteniendo párrafos íntegros.
        pages_raw = _paginate_by_word_count(raw, words_per_page)

    md = _is_markdown(path)
    page_no = 1
    in_code = False
    has_explicit_breaks = len(_PAGE_BREAK.findall(raw)) > 0

    for chunk_idx, chunk in enumerate(pages_raw):
        if not chunk.strip():
            continue
        page_started = False  # marca si ya hubo contenido en esta página lógica
        for raw_line in chunk.split("\n"):
            line = raw_line.rstrip()
            if md and _RE_CODE_FENCE.match(line):
                in_code = not in_code
                out.blocks.append(TextBlock(kind="code", page=page_no, text=line))
                page_started = True
                continue
            if in_code:
                out.blocks.append(TextBlock(kind="code", page=page_no, text=line))
                page_started = True
                continue
            if md:
                m = _RE_HEADING_MD.match(line)
                if m:
                    level = len(m.group(1))
                    title = m.group(2).strip()
                    # Solo promovemos h1 a nueva página si no estamos al inicio
                    # absoluto y no acabamos de entrar a una nueva página por
                    # marcador explícito.
                    if level == 1 and out.blocks and page_started and not has_explicit_breaks:
                        page_no += 1
                        page_started = False
                    out.blocks.append(
                        TextBlock(kind="heading", page=page_no, text=title, level=level)
                    )
                    page_started = True
                    continue
                m = _RE_LIST_MD.match(line)
                if m:
                    out.blocks.append(
                        TextBlock(kind="list", page=page_no, text=m.group(1))
                    )
                    page_started = True
                    continue
            if line.strip():
                out.blocks.append(TextBlock(kind="paragraph", page=page_no, text=line))
                page_started = True
        # Avanzamos la página solo si quedan más chunks reales por venir.
        if chunk_idx + 1 < len(pages_raw):
            out.blocks.append(TextBlock(kind="page_break", page=page_no, text=""))
            page_no += 1

    out.n_pages = max(page_no, 1)
    return out


def _paginate_by_word_count(text: str, words_per_page: int) -> List[str]:
    """Particiona texto en páginas de ~``words_per_page`` palabras respetando
    los límites de párrafo (línea en blanco)."""
    paragraphs = re.split(r"\n\s*\n+", text)
    pages: List[str] = []
    cur: list[str] = []
    cur_words = 0
    for p in paragraphs:
        n = len(p.split())
        if cur and cur_words + n > words_per_page:
            pages.append("\n\n".join(cur))
            cur = [p]
            cur_words = n
        else:
            cur.append(p)
            cur_words += n
    if cur:
        pages.append("\n\n".join(cur))
    return pages or [text]
