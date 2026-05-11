"""Genera un PDF sintético "de estrés" para validar el pipeline de extracción/RAG.

Estructura intencionalmente heterogénea:
  - Portada con metadatos (/Info)
  - Sección a 1 columna con párrafos largos
  - Sección a 2 columnas (Frame + Frame)
  - Sección a 3 columnas
  - Tablas de distinto tamaño/densidad (con encabezado repetido en filas)
  - Gráfica embebida (PNG generado con matplotlib in-memory)
  - Lista numerada y sub-secciones
  - Cabecera/pie repetidos (para probar strip_repeating_page_lines)

Uso:
    py -3 milpa_ai_backend/tools/gen_stress_pdf.py [--out PATH]

El script imprime la ruta absoluta resultante por stdout.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


CANARY_PHRASES = {
    "two_col": "AGUACATILLO_DOSCOLUMNAS_CANARIO_4321 anclaje multicolumna",
    "three_col": "PETUNIA_TRESCOLUMNAS_CANARIO_8765 reflejo en columnas estrechas",
    "table_yield": "JITOMATE_TABLA_RENDIMIENTO_CANARIO_RBR42 marcador en celda",
    "table_dense": "PIPILA_TABLA_DENSA_CANARIO_QWQ73 token en cabecera",
    "chart_legend": "CHIPILIN_FIGURA_CANARIO_LMN15 leyenda incrustada en gráfica",
    "list_item": "MEZQUITE_LISTA_CANARIO_KP9 ítem numerado de control",
    "footer_real": "PIE_REAL_NO_REPETIDO_99",
}

LOREM_BLOCKS = [
    (
        "El sistema agroecológico de la milpa integra maíz, frijol y calabaza en una "
        "misma parcela; cada especie cumple un rol agronómico distinto. El maíz aporta "
        "una estructura vertical sobre la que el frijol trepa, y la calabaza cubre el "
        "suelo conservando humedad y reduciendo malezas. Esta sinergia favorece la "
        "fijación de nitrógeno por el frijol, lo que disminuye la dependencia de "
        "fertilizantes sintéticos en sistemas de bajo insumo."
    ),
    (
        "La fenología local depende del régimen de lluvias y la altitud. En tierras "
        "frías por encima de 2,200 msnm el ciclo se extiende hasta 180 días, mientras "
        "que en planicies subhúmedas se cierra antes de los 130 días. Los productores "
        "ajustan la fecha de siembra a la primera lluvia útil acumulada superior a "
        "30 mm, momento que dispara la emergencia uniforme."
    ),
    (
        "El manejo integrado de plagas combina monitoreo semanal, umbrales económicos, "
        "control biológico con Trichogramma y Bacillus thuringiensis, así como "
        "diversificación con bordes florales para hospedar enemigos naturales. La "
        "rotación con leguminosas reduce inóculo de patógenos del suelo y restaura "
        "materia orgánica."
    ),
    (
        "El balance de macronutrientes sigue una proporción cercana a 4-1-3 (N-P-K) "
        "para maíz en zonas de temporal. La aplicación fraccionada en V6 y V12 mejora "
        "la eficiencia de uso del nitrógeno y reduce pérdidas por volatilización. La "
        "evaluación de pH y materia orgánica orienta encalado y abonos verdes."
    ),
    (
        "La trazabilidad documental del paquete tecnológico exige citar fuentes "
        "primarias revisadas por pares: SAGARPA, INIFAP, CIMMYT, FAO y publicaciones "
        "indexadas. Las recomendaciones operativas deben acompañarse del año de "
        "publicación y la región agroclimática para evitar transferencia indebida."
    ),
]


def _make_chart_png() -> bytes:
    fig, ax = plt.subplots(figsize=(5.6, 3.4), dpi=150)
    cultivos = ["Maíz", "Frijol", "Calabaza", "Amaranto", "Tomate"]
    rendimiento = [7.2, 1.8, 12.3, 1.1, 28.4]
    bars = ax.bar(cultivos, rendimiento, color="#2f6f3f")
    ax.set_ylabel("t/ha (promedio)")
    ax.set_title("Rendimiento promedio por cultivo (zona temporal)")
    for bar, value in zip(bars, rendimiento):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.3,
            f"{value}",
            ha="center",
            fontsize=9,
        )
    ax.text(
        0.5,
        -0.18,
        CANARY_PHRASES["chart_legend"],
        ha="center",
        va="top",
        transform=ax.transAxes,
        fontsize=8,
        color="#444",
    )
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _draw_repeating_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(
        1.5 * cm, doc.pagesize[1] - 0.7 * cm, "MILPA · Documento sintético de estrés"
    )
    canvas.drawRightString(
        doc.pagesize[0] - 1.5 * cm,
        doc.pagesize[1] - 0.7 * cm,
        f"Página {canvas.getPageNumber()}",
    )
    canvas.line(
        1.5 * cm,
        doc.pagesize[1] - 0.85 * cm,
        doc.pagesize[0] - 1.5 * cm,
        doc.pagesize[1] - 0.85 * cm,
    )
    canvas.drawCentredString(
        doc.pagesize[0] / 2.0,
        0.7 * cm,
        "Edición sintética 2026 · prueba de extracción RAG",
    )
    canvas.restoreState()


def _build_styles():
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 13
    styles.add(
        ParagraphStyle(
            "ColBody",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11.5,
            alignment=4,
        )
    )
    styles.add(
        ParagraphStyle(
            "TightCol",
            parent=styles["BodyText"],
            fontSize=8.5,
            leading=10.5,
            alignment=4,
        )
    )
    styles.add(
        ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1f5132"),
            spaceBefore=8,
            spaceAfter=6,
        )
    )
    return styles


def _table_yields() -> Table:
    data: List[List[str]] = [
        ["Cultivo", "Región", "Rendimiento (t/ha)", "Año de referencia"],
        ["Maíz blanco", "Centro (Tlaxcala)", "7.2", "2022"],
        ["Maíz amarillo", "Sinaloa (riego)", "11.4", "2023"],
        ["Frijol negro", "Norte (Zacatecas)", "1.8", "2021"],
        ["Calabaza", "Occidente (Jalisco)", "12.3", "2022"],
        ["Tomate (invernadero)", "Querétaro", "180.0", "2024"],
        [CANARY_PHRASES["table_yield"], "Bajío", "—", "2025"],
    ]
    t = Table(data, colWidths=[4.5 * cm, 5.0 * cm, 3.4 * cm, 3.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde8d8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f8f3")]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return t


def _table_dense() -> Table:
    headers = ["pH", "MO %", "N total %", "P (Olsen) ppm", "K (NH4OAc) cmol", "CE dS/m"]
    body = [
        ["5.2", "1.1", "0.07", "8", "0.18", "0.32"],
        ["5.8", "1.6", "0.09", "12", "0.22", "0.41"],
        ["6.1", "2.0", "0.11", "15", "0.27", "0.55"],
        ["6.4", "2.4", "0.13", "21", "0.31", "0.62"],
        ["6.8", "3.1", "0.16", "28", "0.38", "0.71"],
        ["7.0", "3.4", "0.17", "31", "0.42", "0.79"],
        ["7.2", "3.6", "0.19", "33", "0.45", "0.84"],
        ["7.4", "3.9", "0.21", "37", "0.49", "0.92"],
        ["7.6", "4.1", "0.22", "39", "0.52", "0.97"],
        ["7.8", "4.3", "0.24", "41", "0.55", "1.04"],
    ]
    data = [[CANARY_PHRASES["table_dense"]] + [""] * (len(headers) - 1), headers, *body]
    t = Table(
        data,
        colWidths=[2.5 * cm, 2.5 * cm, 2.6 * cm, 3.0 * cm, 3.4 * cm, 2.4 * cm],
        repeatRows=2,
    )
    t.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f5132")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#cfe0c8")),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#aaaaaa")),
                ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ]
        )
    )
    return t


def _build_one_column_section(styles) -> List:
    flow: List = []
    flow.append(Paragraph("1. Introducción y antecedentes", styles["SectionTitle"]))
    for block in LOREM_BLOCKS[:2]:
        flow.append(Paragraph(block, styles["BodyText"]))
        flow.append(Spacer(1, 0.2 * cm))
    flow.append(
        Paragraph(
            "Este documento sintético combina texto a una, dos y tres columnas; "
            f"tablas heterogéneas; y figuras. Frase canario: <b>{CANARY_PHRASES['list_item']}</b>.",
            styles["BodyText"],
        )
    )
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph("Tabla 1. Rendimiento por cultivo y región.", styles["BodyText"]))
    flow.append(_table_yields())
    flow.append(Spacer(1, 0.3 * cm))
    return flow


def _build_two_column_section(styles) -> List:
    flow: List = []
    flow.append(Paragraph("2. Análisis a doble columna", styles["SectionTitle"]))
    flow.append(
        Paragraph(
            f"Frase canario de doble columna: <b>{CANARY_PHRASES['two_col']}</b>.",
            styles["ColBody"],
        )
    )
    flow.append(Spacer(1, 0.2 * cm))
    for block in LOREM_BLOCKS:
        flow.append(Paragraph(block, styles["ColBody"]))
        flow.append(Spacer(1, 0.18 * cm))
    flow.append(
        Paragraph(
            "Cierre de la sección a 2 columnas; el orden de lectura debe respetarse de "
            "izquierda a derecha y de arriba hacia abajo en cada columna.",
            styles["ColBody"],
        )
    )
    return flow


def _build_three_column_section(styles) -> List:
    flow: List = []
    flow.append(Paragraph("3. Análisis a triple columna", styles["SectionTitle"]))
    # Frase canario en oración corta para que quepa íntegra en una línea estrecha.
    flow.append(
        Paragraph(
            f"Marca canario triple columna {CANARY_PHRASES['three_col']} fin.",
            styles["TightCol"],
        )
    )
    flow.append(Spacer(1, 0.15 * cm))
    flow.extend(Paragraph(block, styles["TightCol"]) for block in LOREM_BLOCKS)
    return flow


def _build_dense_table_section(styles) -> List:
    flow: List = []
    flow.append(Paragraph("3.1 Tabla densa edafológica (1 columna)", styles["SectionTitle"]))
    flow.append(
        Paragraph(
            "La siguiente tabla concentra propiedades del suelo. Frase canario "
            f"asociada: <b>{CANARY_PHRASES['table_dense']}</b>.",
            styles["BodyText"],
        )
    )
    flow.append(Spacer(1, 0.2 * cm))
    flow.append(_table_dense())
    return flow


def _build_chart_section(styles) -> List:
    flow: List = []
    flow.append(Paragraph("4. Gráfica embebida y lista numerada", styles["SectionTitle"]))
    chart_bytes = _make_chart_png()
    flow.append(Image(io.BytesIO(chart_bytes), width=14 * cm, height=8.4 * cm))
    flow.append(
        Paragraph(
            "Figura 1. Rendimiento promedio por cultivo. La leyenda contiene la "
            f"frase canario: <b>{CANARY_PHRASES['chart_legend']}</b>.",
            styles["BodyText"],
        )
    )
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph("Pasos clave del manejo integrado:", styles["BodyText"]))
    items = [
        "Monitoreo semanal con trampas y muestreo destructivo.",
        "Identificación taxonómica con guía y registro fotográfico.",
        "Aplicación de umbrales económicos por etapa fenológica.",
        f"Acción de control biológico — {CANARY_PHRASES['list_item']}.",
        "Evaluación de eficacia y reporte trazable con fuente y año.",
    ]
    for i, it in enumerate(items, start=1):
        flow.append(Paragraph(f"{i}. {it}", styles["BodyText"]))
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(
        Paragraph(
            f"<i>Cierre del documento.</i> Marca de pie real (no debe filtrarse): "
            f"<b>{CANARY_PHRASES['footer_real']}</b>.",
            styles["BodyText"],
        )
    )
    return flow


def build_pdf(out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="MILPA · Documento sintético de estrés",
        author="MILPA Tools",
        subject="Pipeline RAG · validación multi-formato",
    )
    page_w, page_h = LETTER
    usable_w = page_w - 3.0 * cm
    usable_h = page_h - 3.5 * cm
    body_top = page_h - 2.0 * cm
    body_bottom = 1.5 * cm

    one_col = Frame(
        1.5 * cm, body_bottom, usable_w, usable_h, id="single", showBoundary=0
    )
    gutter = 0.6 * cm
    col2_w = (usable_w - gutter) / 2.0
    two_left = Frame(1.5 * cm, body_bottom, col2_w, usable_h, id="left2")
    two_right = Frame(
        1.5 * cm + col2_w + gutter, body_bottom, col2_w, usable_h, id="right2"
    )

    col3_w = (usable_w - 2 * gutter) / 3.0
    three_a = Frame(1.5 * cm, body_bottom, col3_w, usable_h, id="three_a")
    three_b = Frame(
        1.5 * cm + col3_w + gutter, body_bottom, col3_w, usable_h, id="three_b"
    )
    three_c = Frame(
        1.5 * cm + 2 * (col3_w + gutter), body_bottom, col3_w, usable_h, id="three_c"
    )

    doc.addPageTemplates(
        [
            PageTemplate(id="OneCol", frames=[one_col], onPage=_draw_repeating_header_footer),
            PageTemplate(id="TwoCol", frames=[two_left, two_right], onPage=_draw_repeating_header_footer),
            PageTemplate(id="ThreeCol", frames=[three_a, three_b, three_c], onPage=_draw_repeating_header_footer),
        ]
    )

    styles = _build_styles()
    story: List = []
    story.append(NextPageTemplate("OneCol"))
    story.extend(_build_one_column_section(styles))
    story.append(NextPageTemplate("TwoCol"))
    story.append(PageBreak())
    story.extend(_build_two_column_section(styles))
    story.append(NextPageTemplate("ThreeCol"))
    story.append(PageBreak())
    story.extend(_build_three_column_section(styles))
    story.append(NextPageTemplate("OneCol"))
    story.append(PageBreak())
    story.extend(_build_dense_table_section(styles))
    story.append(PageBreak())
    story.extend(_build_chart_section(styles))

    doc.build(story)
    return out_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "stress_pdf_milpa.pdf",
        help="Ruta de salida del PDF",
    )
    args = parser.parse_args(argv)
    out = build_pdf(args.out.resolve())
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
