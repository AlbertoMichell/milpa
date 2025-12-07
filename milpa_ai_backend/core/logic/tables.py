# milpa_ai_backend/core/logic/tables.py
# ------------------------------------------------------------
# Detección/parseo de tablas en PDF:
#   1) Intenta Camelot (lattice/stream) si está instalado y disponible.
#   2) Fallback heurístico con PyMuPDF: usa drawing lines y densidad de spans
#      para aproximar regiones tabulares; parsea a celdas por columnas simples.
# Devuelve estructura con tabla(s), bbox y celdas (row/col/bbox/text)
# lista para persistencia en SQLite (tables/table_cells).
# ------------------------------------------------------------
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple

# Import opcional
try:
    import camelot  # type: ignore
except Exception:
    camelot = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None


def _try_camelot(path: str, pages: str = "1") -> List[Dict[str, Any]]:
    """
    Usa Camelot si está disponible. 'pages' puede ser "1", "1,3,5", "1-5".
    Estructura de salida normalizada: [{page, bbox, cells:[{row,col,text,bbox}...]}]
    """
    if camelot is None:
        return []
    try:
        # lattice mejor con PDFs "digitales" con líneas; stream con texto tabular sin líneas
        tables = camelot.read_pdf(path, pages=pages, flavor="lattice")
        results: List[Dict[str, Any]] = []
        for t in tables:
            # Camelot puede no exponer bbox por celda fácilmente; usamos bbox de tabla.
            bbox = [float(x) for x in t._bbox] if getattr(t, "_bbox", None) else None
            items = []
            df = t.df  # pandas DataFrame
            for r_idx in range(df.shape[0]):
                for c_idx in range(df.shape[1]):
                    items.append({
                        "row": r_idx,
                        "col": c_idx,
                        "text": str(df.iat[r_idx, c_idx]),
                        "bbox": None  # Camelot no da bbox por celda sin trabajo extra
                    })
            results.append({"page": t.parsing_report.get("page", None), "bbox": bbox, "cells": items})
        return results
    except Exception:
        # Si falla, devolvemos vacío para que el fallback intente algo
        return []


def _fallback_detect_tables_pymupdf(path: str, page_numbers: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """
    Fallback ligero con PyMuPDF:
      - Busca dibujos (líneas/rects) y regiones con alta densidad de spans,
        simple heurística para marcar una "tabla".
      - Segmenta por líneas horizontales en forma aproximada.
    NOTA: Esto es un best-effort para MVP y no reemplaza a un parser completo.
    """
    if fitz is None:
        return []

    doc = fitz.open(path)
    pages_to_scan = page_numbers or list(range(1, len(doc) + 1))
    results: List[Dict[str, Any]] = []

    for p_num in pages_to_scan:
        p = doc[p_num - 1]
        drawings = p.get_drawings()  # líneas, rectángulos, etc.
        lines_h = [d for d in drawings if d["items"] and any(i[0] == "l" and abs(i[2] - i[4]) < 1e-3 for i in d["items"])]
        lines_v = [d for d in drawings if d["items"] and any(i[0] == "l" and abs(i[3] - i[5]) < 1e-3 for i in d["items"])]

        # Si hay líneas horizontales y verticales suficientes, asumimos tabla
        if len(lines_h) >= 2 and len(lines_v) >= 2:
            # bbox grueso: bounding box de todos los drawings
            xs, ys = [], []
            for d in drawings:
                bbox = d.get("rect")
                if bbox:
                    xs += [bbox.x0, bbox.x1]
                    ys += [bbox.y0, bbox.y1]
            if xs and ys:
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            else:
                bbox = None

            # Segmentación naive por filas (orden vertical)
            # Extrae texto por bloques y los asigna a "filas" por bandas horizontales
            text_blocks = p.get_text("blocks")
            text_blocks = sorted(text_blocks, key=lambda b: b[1])  # y0 asc
            rows: Dict[int, List[Tuple[float, float, float, float, str]]] = {}
            current_row = 0
            last_y = None
            for b in text_blocks:
                x0, y0, x1, y1, text, *_ = b
                if last_y is None or abs(y0 - last_y) < 8.0:
                    rows.setdefault(current_row, []).append((x0, y0, x1, y1, text))
                    last_y = y0
                else:
                    current_row += 1
                    rows.setdefault(current_row, []).append((x0, y0, x1, y1, text))
                    last_y = y0

            # Aplanar a "cells" por columnas aproximadas (2-4 cols heurísticas)
            cells: List[Dict[str, Any]] = []
            for r_idx, items in rows.items():
                # ordenar por x0 asc
                items = sorted(items, key=lambda it: it[0])
                # agrupar en N columnas simples
                if not items:
                    continue
                # split en ~3 columnas por ranks de x0
                xs_sorted = sorted([it[0] for it in items])
                if len(xs_sorted) < 3:
                    cuts = [float("inf")]
                else:
                    # 3 columnas -> 2 cortes percentiles 33 y 66
                    p33 = xs_sorted[int(0.33 * len(xs_sorted))]
                    p66 = xs_sorted[int(0.66 * len(xs_sorted))]
                    cuts = [p33, p66, float("inf")]
                col = 0
                col_map: Dict[int, List[Tuple[float, float, float, float, str]]] = {0: [], 1: [], 2: []}
                for it in items:
                    x0 = it[0]
                    if x0 <= cuts[0]:
                        col_map[0].append(it)
                    elif x0 <= cuts[1]:
                        col_map[1].append(it)
                    else:
                        col_map[2].append(it)
                for c_idx in sorted(col_map.keys()):
                    if not col_map[c_idx]:
                        continue
                    # bbox de la "celda" ~ envolvente
                    xs = [x0 for x0, *_ in col_map[c_idx]]
                    ys0 = [y0 for _, y0, *_ in col_map[c_idx]]
                    xs1 = [x1 for *_, x1, _, __ in col_map[c_idx]]
                    ys1 = [y1 for *_, y1, __ in col_map[c_idx]]
                    cell_bbox = [min(xs), min(ys0), max(xs1), max(ys1)]
                    cell_text = " ".join([t.strip() for *_, t in col_map[c_idx] if t.strip()])
                    cells.append({"row": r_idx, "col": c_idx, "text": cell_text, "bbox": cell_bbox})

            results.append({"page": p_num, "bbox": bbox, "cells": cells})

    return results


def detect_and_parse_tables_pdf(path: str, pages: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """
    Detecta y parsea tablas:
      - Camelot primero (si disponible).
      - Fallback PyMuPDF heurístico.
    """
    # Camelot permite '1-5', etc. Si no se especifica, procesamos todas.
    if camelot is not None and pages is None:
        try:
            total = _try_camelot(path, pages="all")
            if total:
                return total
        except Exception:
            pass

    # Camelot por páginas específicas
    if camelot is not None and pages:
        page_str = ",".join(str(p) for p in pages)
        try:
            total = _try_camelot(path, pages=page_str)
            if total:
                return total
        except Exception:
            pass

    # Fallback PyMuPDF
    return _fallback_detect_tables_pymupdf(path, page_numbers=pages or None)
