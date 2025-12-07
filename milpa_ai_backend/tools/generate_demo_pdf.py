"""
Genera un PDF sencillo con tablas genéricas del sistema MILPA, sin dependencias externas.
Salida: ../data/documents/demo_biblioteca_tablas.pdf
"""
from __future__ import annotations

from pathlib import Path


def esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf() -> bytes:
    # Cabecera PDF
    parts: list[bytes] = []
    def b(x: str) -> bytes:
        return x.encode("latin-1", errors="ignore")

    parts.append(b("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n"))

    objects: list[bytes] = []

    # 1: Catalog
    objects.append(b("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"))
    # 2: Pages
    objects.append(b("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"))
    # 5: Helvetica font
    objects.append(b("5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"))

    # 4: Content stream (lo llenamos luego con /Length correcto)
    lines: list[str] = []
    def text_at(x: int, y: int, text: str):
        lines.append(f"1 0 0 1 {x} {y} Tm ({esc(text)}) Tj\n")

    # Contenido
    lines.append("BT\n/F1 16 Tf\n")
    text_at(72, 740, "MILPA - Tablas de prueba")
    lines.append("/F1 12 Tf\n")
    text_at(72, 720, "Autor: Equipo MILPA | Ano: 2025")

    # Tabla 1: Rendimientos
    text_at(72, 690, "Tabla 1: Rendimientos promedio t/ha")
    # Encabezados
    text_at(72, 672, "Cultivo")
    text_at(200, 672, "Region")
    text_at(380, 672, "Rendimiento")
    # Filas
    text_at(72, 656, "Maiz")
    text_at(200, 656, "Centro")
    text_at(380, 656, "7.2")
    text_at(72, 642, "Maiz")
    text_at(200, 642, "Sur-Sureste")
    text_at(380, 642, "4.8")
    text_at(72, 628, "Frijol")
    text_at(200, 628, "Norte")
    text_at(380, 628, "1.8")
    text_at(72, 614, "Calabaza")
    text_at(200, 614, "Occidente")
    text_at(380, 614, "12.3")

    # Tabla 2: Asociaciones
    text_at(72, 590, "Tabla 2: Asociaciones MILPA")
    text_at(72, 572, "Asociacion")
    text_at(220, 572, "Objetivo")
    text_at(400, 572, "Beneficio")
    text_at(72, 556, "Maiz + Frijol")
    text_at(220, 556, "Fijacion N")
    text_at(400, 556, "Mejora fertilidad")
    text_at(72, 542, "Maiz + Calabaza")
    text_at(220, 542, "Cobertura")
    text_at(400, 542, "Menos malezas")
    text_at(72, 528, "Maiz + Frijol + Calabaza")
    text_at(220, 528, "Policultivo")
    text_at(400, 528, "Resiliencia")

    # Tabla 3: Fenologia
    text_at(72, 504, "Tabla 3: Calendario fenologico")
    text_at(72, 486, "Cultivo")
    text_at(160, 486, "Siembra")
    text_at(240, 486, "Emerg.")
    text_at(320, 486, "Florac.")
    text_at(400, 486, "Cosecha")
    text_at(72, 470, "Maiz")
    text_at(160, 470, "Abr-May")
    text_at(240, 470, "7-10 d")
    text_at(320, 470, "60-75 d")
    text_at(400, 470, "100-130 d")
    text_at(72, 456, "Frijol")
    text_at(160, 456, "May-Jun")
    text_at(240, 456, "5-8 d")
    text_at(320, 456, "35-45 d")
    text_at(400, 456, "80-100 d")

    # Tabla 4: Nutrientes
    text_at(72, 432, "Tabla 4: Nutrientes y fuentes")
    text_at(72, 414, "Nutriente")
    text_at(200, 414, "Deficiencia")
    text_at(360, 414, "Fuente org.")
    text_at(72, 398, "N")
    text_at(200, 398, "Clorosis")
    text_at(360, 398, "Compost, abono verde")
    text_at(72, 384, "P")
    text_at(200, 384, "Lento crec.")
    text_at(360, 384, "Fosfatos nat., hueso")
    text_at(72, 370, "K")
    text_at(200, 370, "Borde quemado")
    text_at(360, 370, "Ceniza vegetal")

    # Tabla 5: Plagas
    text_at(72, 346, "Tabla 5: Plagas y MIP")
    text_at(72, 328, "Plaga")
    text_at(200, 328, "Sintoma")
    text_at(360, 328, "Manejo")
    text_at(72, 312, "Cogollero")
    text_at(200, 312, "Dano en cogollo")
    text_at(360, 312, "BT, trampas, retiro")
    text_at(72, 298, "Pulgones")
    text_at(200, 298, "Mielada")
    text_at(360, 298, "Jabon pot., neem")

    lines.append("ET\n")
    content = ("".join(lines)).encode("latin-1", errors="ignore")
    content_obj = b(f"4 0 obj\n<< /Length {len(content)} >>\nstream\n") + content + b("endstream\nendobj\n")

    # 3: Page (después de tener 5 y 4)
    page_obj = b("3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n")

    # Orden: 1,2,3,4,5
    objects_ordered = [objects[0], objects[1], page_obj, content_obj, objects[2]]

    # Construimos offsets
    offsets = []
    current = sum(len(p) for p in parts)
    for obj in objects_ordered:
        offsets.append(current)
        current += len(obj)

    # Ensamblar cuerpo
    for obj in objects_ordered:
        parts.append(obj)

    # xref
    xref_pos = sum(len(p) for p in parts)
    xref = ["xref\n", "0 6\n", "0000000000 65535 f \n"]
    for off in offsets:
        xref.append(f"{off:010d} 00000 n \n")
    parts.append(b("".join(xref)))

    # trailer y startxref
    parts.append(b("trailer\n<< /Size 6 /Root 1 0 R >>\n"))
    parts.append(b(f"startxref\n{xref_pos}\n%%EOF\n"))

    return b("").join(parts)  # type: ignore


def main():
    out = Path(__file__).resolve().parent.parent / "data" / "documents" / "demo_biblioteca_tablas.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = build_pdf()
    out.write_bytes(pdf_bytes)
    print(f"Escrito: {out} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
