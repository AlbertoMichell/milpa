"""Genera un PDF sintetico con informacion agricola y tablas."""
from fpdf import FPDF

OUT = "cultivos_sintetico.pdf"

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, "Guia Tecnica de Cultivos - Edicion Sintetica 2025", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")

    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_fill_color(34, 120, 60)
        self.set_text_color(255)
        self.cell(0, 9, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0)
        self.ln(3)

    def section(self, title):
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, txt):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5, txt)
        self.ln(2)

    def add_table(self, headers, rows, col_widths=None):
        if col_widths is None:
            w = (self.w - 20) / len(headers)
            col_widths = [w] * len(headers)
        # header
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(220, 230, 220)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        self.ln()
        # rows
        self.set_font("Helvetica", "", 9)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(245, 250, 245)
            for i, val in enumerate(row):
                self.cell(col_widths[i], 6, str(val), border=1, fill=fill, align="C")
            self.ln()
            fill = not fill
        self.ln(3)


pdf = PDF()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)

# ============================================================
# PAGINA 1 - Maiz
# ============================================================
pdf.add_page()
pdf.chapter_title("1. Maiz (Zea mays L.)")

pdf.section("1.1 Descripcion general")
pdf.body(
    "El maiz es una graminea anual originaria de Mesoamerica y constituye "
    "el cultivo mas importante de Mexico, con una superficie sembrada superior "
    "a 7.5 millones de hectareas. Se adapta a altitudes desde el nivel del mar "
    "hasta 3,000 msnm. Las variedades criollas de la milpa tradicional presentan "
    "ciclos vegetativos de 120 a 180 dias, mientras que los hibridos comerciales "
    "maduran en 90 a 140 dias."
)

pdf.section("1.2 Requerimientos edafoclimaticos")
pdf.body(
    "Temperatura optima: 20-30 C. El maiz requiere suelos francos a "
    "franco-arcillosos con pH entre 5.5 y 7.0 y materia organica superior al 2%. "
    "La precipitacion ideal es de 500-800 mm distribuidos durante el ciclo. "
    "Es sensible a heladas y encharcamiento prolongado."
)

pdf.section("1.3 Fertilizacion recomendada")
pdf.body("La siguiente tabla resume las dosis de fertilizacion por tipo de suelo:")

pdf.add_table(
    ["Tipo de suelo", "N (kg/ha)", "P2O5 (kg/ha)", "K2O (kg/ha)", "Rendimiento esperado"],
    [
        ["Franco arenoso", "140", "60", "40", "4.5 ton/ha"],
        ["Franco", "120", "50", "30", "5.2 ton/ha"],
        ["Franco arcilloso", "100", "40", "20", "4.8 ton/ha"],
        ["Arcilloso", "90", "45", "25", "3.9 ton/ha"],
        ["Vertisol", "130", "55", "35", "5.0 ton/ha"],
    ],
    [35, 28, 32, 32, 40],
)

pdf.section("1.4 Principales plagas y enfermedades")
pdf.add_table(
    ["Plaga / Enfermedad", "Agente causal", "Dano", "Control recomendado"],
    [
        ["Gusano cogollero", "Spodoptera frugiperda", "Defoliacion 30-70%", "Bt, Spinosad"],
        ["Gusano elotero", "Helicoverpa zea", "Dano en elote 15-40%", "Trampas, Bt"],
        ["Roya comun", "Puccinia sorghi", "Reduccion 10-25%", "Variedades resistentes"],
        ["Carbon de espiga", "Sporisorium reilianum", "Perdida total espiga", "Semilla tratada"],
        ["Chapulin", "Sphenarium spp.", "Defoliacion variable", "Control biologico"],
    ],
    [38, 42, 42, 45],
)

# ============================================================
# PAGINA 2 - Frijol
# ============================================================
pdf.add_page()
pdf.chapter_title("2. Frijol (Phaseolus vulgaris L.)")

pdf.section("2.1 Descripcion general")
pdf.body(
    "El frijol es la leguminosa de grano mas importante en la dieta mexicana, "
    "con un consumo per capita de 10.7 kg/anio. Se cultivan cerca de 1.8 millones "
    "de hectareas, principalmente en temporal. Las variedades de mata (arbustivas) "
    "dominan la produccion comercial, mientras que las de guia (trepadoras) se "
    "asocian con maiz en la milpa. La fijacion biologica de nitrogeno aporta "
    "entre 40 y 80 kg N/ha al sistema, beneficiando cultivos subsecuentes."
)

pdf.section("2.2 Variedades por region")
pdf.add_table(
    ["Variedad", "Region", "Ciclo (dias)", "Color grano", "Rendimiento (kg/ha)"],
    [
        ["Negro Jamapa", "Golfo", "85-90", "Negro", "1,200"],
        ["Pinto Saltillo", "Altiplano Norte", "95-100", "Pinto", "1,800"],
        ["Flor de Mayo", "Altiplano Central", "100-110", "Rosa claro", "1,500"],
        ["Azufrado Higuera", "Noroeste", "80-85", "Amarillo", "2,100"],
        ["Bayo Madero", "Bajio", "90-95", "Bayo", "1,600"],
        ["Peruano", "Sinaloa", "75-80", "Amarillo claro", "2,300"],
    ],
    [35, 32, 28, 30, 38],
)

pdf.section("2.3 Fertilizacion")
pdf.body(
    "Dado que el frijol fija nitrogeno, las dosis de N son menores que en "
    "cereales. Se recomienda una fertilizacion base de 30-40 kg N/ha como "
    "arrancador, 40-60 kg P2O5/ha y 20-30 kg K2O/ha. La inoculacion con "
    "Rhizobium etli incrementa la fijacion en un 25-40% respecto a suelos "
    "sin inoculo. En suelos acidos (pH < 5.5) se recomienda encalado con "
    "1-2 ton/ha de cal dolomita previo a la siembra."
)

pdf.section("2.4 Plagas del frijol")
pdf.add_table(
    ["Plaga", "Nombre cientifico", "Etapa critica", "Umbral economico"],
    [
        ["Conchuela", "Epilachna varivestis", "Floracion", "2 adultos/planta"],
        ["Chicharrita", "Empoasca kraemeri", "Vegetativo", "3 ninfas/hoja"],
        ["Mosca blanca", "Bemisia tabaci", "Todo el ciclo", "5 adultos/hoja"],
        ["Picudo del ejote", "Apion godmani", "Fructificacion", "1 adulto/planta"],
    ],
    [35, 40, 35, 40],
)

# ============================================================
# PAGINA 3 - Calabaza
# ============================================================
pdf.add_page()
pdf.chapter_title("3. Calabaza (Cucurbita spp.)")

pdf.section("3.1 Especies cultivadas en Mexico")
pdf.body(
    "Mexico es centro de origen de al menos cuatro especies de calabaza "
    "domesticadas: C. pepo, C. moschata, C. argyrosperma y C. ficifolia. "
    "La calabaza en la milpa cumple funciones de cobertura del suelo, "
    "reduccion de evapotranspiracion (hasta 30%) y supresion de malezas. "
    "Las semillas (pepitas) tienen alto valor nutricional con 30% de proteina "
    "y 45% de aceite."
)

pdf.add_table(
    ["Especie", "Nombre comun", "Uso principal", "Altitud (msnm)", "Ciclo (dias)"],
    [
        ["C. pepo", "Calabacita", "Fruto tierno", "0-2,500", "45-60"],
        ["C. moschata", "Calabaza de Castilla", "Fruto maduro, dulce", "0-1,800", "120-150"],
        ["C. argyrosperma", "Calabaza pipiana", "Semilla (pepita)", "0-1,500", "100-130"],
        ["C. ficifolia", "Chilacayote", "Dulce, medicinal", "1,500-3,000", "150-210"],
    ],
    [30, 38, 35, 30, 28],
)

pdf.section("3.2 Nutricion del cultivo")
pdf.body(
    "La calabaza requiere suelos ricos en materia organica (>3%). Se recomienda "
    "aplicar 80-100 kg N/ha, 60-80 kg P2O5/ha y 80-100 kg K2O/ha. La aplicacion "
    "de composta a razon de 5-10 ton/ha mejora la estructura del suelo y la "
    "retencion de humedad. El potasio es critico durante la fructificacion para "
    "el llenado de fruto y calidad de semilla."
)

# ============================================================
# PAGINA 4 - Chile y Tomate
# ============================================================
pdf.add_page()
pdf.chapter_title("4. Chile (Capsicum annuum L.)")

pdf.section("4.1 Descripcion")
pdf.body(
    "Mexico es centro de diversidad del genero Capsicum con mas de 64 tipos "
    "de chile documentados. La produccion nacional supera 3.2 millones de "
    "toneladas anuales. Los tipos mas cultivados son jalapeno, serrano, "
    "habanero, ancho/poblano, guajillo y de arbol."
)

pdf.section("4.2 Requerimientos nutricionales por tipo de chile")
pdf.add_table(
    ["Tipo de chile", "N (kg/ha)", "P2O5 (kg/ha)", "K2O (kg/ha)", "Rend. (ton/ha)"],
    [
        ["Jalapeno", "180", "80", "120", "25-35"],
        ["Serrano", "160", "70", "100", "15-20"],
        ["Habanero", "200", "90", "150", "30-40"],
        ["Ancho/Poblano", "150", "65", "90", "12-18"],
        ["Guajillo", "140", "60", "85", "8-12"],
        ["De arbol", "130", "55", "80", "6-10"],
    ],
    [35, 28, 32, 32, 32],
)

pdf.chapter_title("5. Tomate (Solanum lycopersicum L.)")

pdf.section("5.1 Produccion y nutricion")
pdf.body(
    "Mexico es el decimo productor mundial de tomate con 3.4 millones de "
    "toneladas. El cultivo requiere 200-250 kg N/ha, 100-150 kg P2O5/ha "
    "y 200-300 kg K2O/ha para rendimientos comerciales de 60-80 ton/ha en "
    "campo abierto y hasta 150 ton/ha en invernadero. El tomate es muy "
    "sensible a la salinidad (CE max 2.5 dS/m) y al deficit de calcio, "
    "que causa pudricion apical (blossom end rot)."
)

# ============================================================
# PAGINA 5 - Suelos y tabla resumen
# ============================================================
pdf.add_page()
pdf.chapter_title("6. Analisis comparativo de nutricion")

pdf.section("6.1 Tabla resumen de fertilizacion por cultivo")
pdf.add_table(
    ["Cultivo", "N (kg/ha)", "P2O5 (kg/ha)", "K2O (kg/ha)", "pH optimo", "M.O. min (%)"],
    [
        ["Maiz", "90-140", "40-60", "20-40", "5.5-7.0", "2.0"],
        ["Frijol", "30-40", "40-60", "20-30", "5.8-7.0", "2.5"],
        ["Calabaza", "80-100", "60-80", "80-100", "6.0-7.5", "3.0"],
        ["Chile", "130-200", "55-90", "80-150", "6.0-7.0", "2.5"],
        ["Tomate", "200-250", "100-150", "200-300", "5.8-6.8", "3.0"],
        ["Sorgo", "100-120", "40-50", "30-40", "5.5-7.5", "1.5"],
        ["Trigo", "120-160", "50-70", "30-50", "6.0-7.5", "2.0"],
        ["Arroz", "80-120", "30-50", "30-60", "5.0-6.5", "2.0"],
    ],
    [28, 28, 32, 32, 25, 25],
)

pdf.section("6.2 Interpretacion de analisis de suelo")
pdf.add_table(
    ["Parametro", "Bajo", "Medio", "Alto", "Unidad"],
    [
        ["Nitrogeno total", "< 0.10", "0.10 - 0.15", "> 0.15", "% peso"],
        ["Fosforo Olsen", "< 10", "10 - 20", "> 20", "mg/kg"],
        ["Potasio intercambiable", "< 150", "150 - 300", "> 300", "mg/kg"],
        ["Materia organica", "< 2.0", "2.0 - 4.0", "> 4.0", "%"],
        ["pH", "< 5.5 (acido)", "5.5 - 7.0", "> 7.0 (alcalino)", "unidades"],
        ["CE", "< 1.0", "1.0 - 2.0", "> 2.0", "dS/m"],
        ["CIC", "< 10", "10 - 25", "> 25", "cmol/kg"],
    ],
    [38, 25, 30, 30, 28],
)

pdf.section("6.3 Rotaciones recomendadas")
pdf.body(
    "Las rotaciones de cultivo mejoran la fertilidad del suelo y rompen ciclos "
    "de plagas. Se recomienda:\n"
    "- Milpa (maiz-frijol-calabaza) seguida de abono verde (Crotalaria o Mucuna)\n"
    "- Maiz - Frijol - Avena (cobertura invernal)\n"
    "- Chile - Maiz - Frijol (ciclo de 3 anios)\n"
    "- Tomate - Maiz - Leguminosa (evitar solanaceas consecutivas)\n\n"
    "La inclusion de leguminosas cada 2-3 ciclos aporta 40-80 kg N/ha al sistema "
    "y mejora la estructura del suelo."
)

pdf.output(OUT)
print(f"PDF generado: {OUT}")
