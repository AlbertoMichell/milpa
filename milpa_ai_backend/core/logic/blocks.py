"""Extracción de bloques con bbox y orden de lectura multi-columna.

Este módulo eleva el granularidad del extractor de **página** a **bloque**:
para cada página devuelve la lista de bloques de PyMuPDF con su bbox normalizado
(``(x0,y0,x1,y1)``) y un texto ya pasado por ``normalize_extracted_text``. La
ordenación reproduce la lectura humana en layouts de 1, 2 y 3 columnas usando
detección de "gaps" verticales reales (huecos entre centros X).

Salida pensada para que el extractor agrupe bloques contiguos en fragmentos del
tamaño deseado y persista cada fragmento con la **unión** de bboxes que lo
componen: así el visor puede dibujar overlays exactos sobre la página
renderizada y las citas RAG indican zonas, no toda la página.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from milpa_ai_backend.core.logic.extract_layout import normalize_extracted_text


@dataclass
class TextLine:
    """Línea de texto con bbox propio (en coordenadas PDF)."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def char_count(self) -> int:
        return len(self.text or "")


@dataclass
class Block:
    """Bloque de texto con coordenadas en el espacio del PDF (puntos)."""
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    column: int = 0  # 0..(n_cols-1) tras la asignación
    seq_in_page: int = 0
    block_no: int = -1  # índice original devuelto por PyMuPDF
    n_cols_detected: int = 1
    # Líneas que componen el bloque, cada una con su propio bbox. Esto permite
    # que el caller subdivida un bloque grande en sub-chunks con bbox precisos
    # (no solo el bbox padre).
    lines: List[TextLine] = field(default_factory=list)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.0)

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 0.0)

    @property
    def char_count(self) -> int:
        return len(self.text or "")


@dataclass
class PageBlocks:
    """Conjunto de bloques de una página, ya ordenados para lectura."""
    page: int
    width: float
    height: float
    blocks: List[Block] = field(default_factory=list)
    n_cols: int = 1


def _raw_blocks(page: fitz.Page) -> List[Block]:
    """Carga los bloques tipo 0 (texto) de PyMuPDF, cada uno con sus líneas."""
    out: List[Block] = []
    try:
        d = page.get_text("dict") or {}
    except Exception:
        return out
    page_no = page.number + 1
    for idx, block in enumerate(d.get("blocks") or []):
        if block.get("type") != 0:
            continue
        bb = block.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        if len(bb) < 4:
            continue
        x0, y0, x1, y1 = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        text_chunks: List[str] = []
        line_objs: List[TextLine] = []
        for line in block.get("lines") or []:
            line_pieces: List[str] = []
            for sp in line.get("spans") or []:
                t = sp.get("text") or ""
                if t:
                    line_pieces.append(t)
            if not line_pieces:
                continue
            ltext_raw = "".join(line_pieces)
            ltext = normalize_extracted_text(ltext_raw)
            if not ltext.strip():
                continue
            text_chunks.append(ltext_raw)
            lbb = line.get("bbox") or [x0, y0, x1, y1]
            try:
                lx0, ly0, lx1, ly1 = float(lbb[0]), float(lbb[1]), float(lbb[2]), float(lbb[3])
            except Exception:
                lx0, ly0, lx1, ly1 = x0, y0, x1, y1
            line_objs.append(TextLine(x0=lx0, y0=ly0, x1=lx1, y1=ly1, text=ltext))
        text = normalize_extracted_text("\n".join(text_chunks))
        if not text or len(text.strip()) < 2:
            continue
        out.append(
            Block(
                page=page_no,
                x0=x0, y0=y0, x1=x1, y1=y1,
                text=text,
                block_no=idx,
                lines=line_objs,
            )
        )
    return out


def _detect_n_columns(
    blocks: List[Block],
    page_width: float,
) -> Tuple[int, Optional[List[float]]]:
    """Devuelve ``(n_cols, cuts)`` donde ``cuts`` son las x que separan columnas.

    Estrategia: si la varianza horizontal es alta y existen 2 (o 3) huecos
    significativos entre los centros X de los bloques, se interpreta como
    multi-columna. ``cuts`` está expresado en coordenadas del PDF.

    El umbral de "hueco significativo" exige al menos 8% del ancho de la
    página, igual que la heurística de ``extract_layout._detect_column_breaks``.
    """
    if len(blocks) < 4:
        return 1, None
    centers = sorted(b.x_center for b in blocks)
    if statistics.stdev(centers) < page_width * 0.10:
        return 1, None
    threshold = max(page_width * 0.08, 30.0)

    def _cuts_for(n: int) -> Optional[List[float]]:
        if n < 2 or len(centers) < n * 2:
            return None
        gaps = sorted(
            (
                (centers[i + 1] - centers[i], (centers[i + 1] + centers[i]) / 2.0)
                for i in range(len(centers) - 1)
            ),
            key=lambda kv: kv[0],
            reverse=True,
        )
        chosen = gaps[: n - 1]
        if any(g[0] < threshold for g in chosen):
            return None
        return sorted(g[1] for g in chosen)

    # Probamos primero 3 columnas; si falla, 2.
    cuts3 = _cuts_for(3)
    if cuts3 is not None:
        return 3, cuts3
    cuts2 = _cuts_for(2)
    if cuts2 is not None:
        return 2, cuts2
    return 1, None


def _assign_column(b: Block, cuts: Optional[List[float]], n_cols: int) -> int:
    if not cuts or n_cols < 2:
        return 0
    cx = b.x_center
    idx = 0
    while idx < n_cols - 1 and cx >= cuts[idx]:
        idx += 1
    return idx


def _full_width_block(b: Block, page_width: float) -> bool:
    """¿Es un bloque que ocupa todo el ancho (probable título de sección)?"""
    return (b.width / max(page_width, 1.0)) >= 0.78


def order_blocks_for_reading(
    blocks: List[Block],
    page_width: float,
) -> Tuple[List[Block], int]:
    """Devuelve los bloques en orden de lectura humana y ``n_cols`` detectado.

    Reglas:
      1. Detectamos ``n_cols`` por gaps reales. Si es 1, ordenamos por
         ``(y0, x0)``.
      2. Si es 2/3, los bloques con anchura ≥ 78% del ancho de página
         (títulos de sección, banners) se mantienen como "anchos" en su
         posición vertical original; los demás se asignan a columnas y se
         ordenan por (columna, y0). Luego mezclamos preservando orden vertical
         entre los anchos y los bloques de cada columna.
    """
    if not blocks:
        return [], 1
    n_cols, cuts = _detect_n_columns(blocks, page_width)
    if n_cols == 1:
        ordered = sorted(blocks, key=lambda b: (b.y0, b.x0))
        for i, b in enumerate(ordered):
            b.column = 0
            b.seq_in_page = i
            b.n_cols_detected = 1
        return ordered, 1

    wide: List[Block] = []
    cols: List[List[Block]] = [[] for _ in range(n_cols)]
    for b in blocks:
        if _full_width_block(b, page_width):
            wide.append(b)
        else:
            c = _assign_column(b, cuts, n_cols)
            b.column = c
            cols[c].append(b)
    for cl in cols:
        cl.sort(key=lambda b: (b.y0, b.x0))

    # Si una columna queda vacía (heurística agresiva), regresamos al modo "todo
    # mezclado" en orden y simple — más seguro que perder bloques.
    if any(not cl for cl in cols):
        ordered = sorted(blocks, key=lambda b: (b.y0, b.x0))
        for i, b in enumerate(ordered):
            b.column = 0
            b.seq_in_page = i
            b.n_cols_detected = 1
        return ordered, 1

    wide.sort(key=lambda b: b.y0)
    # Mezclamos: para cada bloque ancho, vacíamos los bloques de cada columna
    # cuyo y0 sea menor (van antes) y luego añadimos el bloque ancho.
    iters = [iter(cl) for cl in cols]
    next_in_col: List[Optional[Block]] = [next(it, None) for it in iters]
    out: List[Block] = []
    wide_idx = 0
    while any(b is not None for b in next_in_col) or wide_idx < len(wide):
        wide_y = wide[wide_idx].y0 if wide_idx < len(wide) else float("inf")
        # Antes del próximo bloque ancho, vaciamos todos los de columnas con y < wide_y
        # respetando el orden columna-y dentro de la franja.
        progress = True
        while progress:
            progress = False
            # Recorremos columnas en orden 0..n y dentro tomamos su próximo bloque
            # solo si su y0 < wide_y; así aseguramos que un párrafo en la col 0
            # alimente todo lo de la franja antes de pasar a col 1.
            for ci in range(n_cols):
                while next_in_col[ci] is not None and next_in_col[ci].y0 < wide_y:
                    out.append(next_in_col[ci])  # type: ignore[arg-type]
                    next_in_col[ci] = next(iters[ci], None)
                    progress = True
        if wide_idx < len(wide):
            out.append(wide[wide_idx])
            wide_idx += 1
    for i, b in enumerate(out):
        b.seq_in_page = i
        b.n_cols_detected = n_cols
    return out, n_cols


def page_blocks(page: fitz.Page) -> PageBlocks:
    """Pipeline público: extrae bloques + ordena multi-columna.

    El caller usa ``PageBlocks.blocks`` para fragmentar agrupando bloques
    contiguos hasta el tamaño objetivo, y obtiene el bbox real de cada
    fragmento usando ``union_bbox``.
    """
    pw = float(getattr(page.rect, "width", 0.0) or 0.0) or 1.0
    ph = float(getattr(page.rect, "height", 0.0) or 0.0) or 1.0
    raw = _raw_blocks(page)
    ordered, n_cols = order_blocks_for_reading(raw, pw)
    return PageBlocks(page=page.number + 1, width=pw, height=ph, blocks=ordered, n_cols=n_cols)


def union_bbox(bs: List[Block]) -> Tuple[float, float, float, float]:
    """Bbox que cubre todos los bloques pasados (devuelve (0,0,0,0) si vacío)."""
    if not bs:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b.x0 for b in bs),
        min(b.y0 for b in bs),
        max(b.x1 for b in bs),
        max(b.y1 for b in bs),
    )


def union_line_bbox(lines: List[TextLine]) -> Tuple[float, float, float, float]:
    """Bbox que cubre las líneas pasadas."""
    if not lines:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(l.x0 for l in lines),
        min(l.y0 for l in lines),
        max(l.x1 for l in lines),
        max(l.y1 for l in lines),
    )


def collect_lines(blocks: List[Block]) -> List[TextLine]:
    """Concatena las líneas de varios bloques preservando el orden de lectura.

    Si un bloque no tiene líneas (por ejemplo OCR full-page), genera una línea
    sintética con el bbox del bloque y el texto completo.
    """
    out: List[TextLine] = []
    for b in blocks:
        if b.lines:
            out.extend(b.lines)
        else:
            out.append(TextLine(x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1, text=b.text))
    return out


def subdivide_lines_by_chars(
    lines: List[TextLine],
    target_chars: int,
    *,
    soft_factor: float = 1.4,
) -> List[List[TextLine]]:
    """Particiona la lista de líneas en grupos cuya suma de caracteres no
    exceda ``target_chars * soft_factor`` y trate de quedar cerca del target.

    Permite construir sub-chunks cuyo bbox es la unión de los bboxes de las
    líneas que los componen — bbox real, no el bbox padre del bloque.
    """
    if target_chars <= 0:
        target_chars = 600
    soft_max = int(target_chars * soft_factor)
    out: List[List[TextLine]] = []
    cur: List[TextLine] = []
    cur_n = 0
    for ln in lines:
        ln_chars = ln.char_count
        if cur and (cur_n + ln_chars > soft_max):
            out.append(cur)
            cur = [ln]
            cur_n = ln_chars
        else:
            cur.append(ln)
            cur_n += ln_chars
        if cur_n >= target_chars:
            out.append(cur)
            cur = []
            cur_n = 0
    if cur:
        out.append(cur)
    return out


def group_blocks_into_chunks(
    blocks: List[Block],
    target_chars: int,
    *,
    soft_chars_factor: float = 1.25,
) -> List[List[Block]]:
    """Agrupa bloques contiguos hasta sumar ``target_chars`` (caracteres).

    Si un bloque supera por sí solo ``target_chars * soft_chars_factor``, lo
    dejamos como su propio grupo (el caller lo dividirá por palabras/líneas).

    Este algoritmo respeta el orden original y NO mezcla bloques de columnas
    distintas con un bloque "ancho" en medio: un bloque ancho cierra el grupo
    actual.
    """
    if target_chars <= 0:
        target_chars = 1200
    soft_max = int(target_chars * soft_chars_factor)
    out: List[List[Block]] = []
    cur: List[Block] = []
    cur_chars = 0
    for b in blocks:
        is_wide = b.n_cols_detected > 1 and (
            (b.x1 - b.x0) / max((b.x1 - b.x0), 1.0)
        )
        # Heurística simple: cierre por bloque ancho cuando hay multi-col.
        wide_break = False
        if cur and b.n_cols_detected > 1:
            if (b.x1 - b.x0) > 0 and (b.x1 - b.x0) >= 0.7 * max(
                (max(c.x1 for c in cur) - min(c.x0 for c in cur)), 1.0
            ):
                wide_break = True

        if cur and (cur_chars + b.char_count > soft_max or wide_break):
            out.append(cur)
            cur = [b]
            cur_chars = b.char_count
        else:
            cur.append(b)
            cur_chars += b.char_count

        if cur_chars >= target_chars:
            out.append(cur)
            cur = []
            cur_chars = 0
    if cur:
        out.append(cur)
    return out
