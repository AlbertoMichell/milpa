"""Genera un Markdown de estrés con encabezados h1/h2/h3, listas y form-feed.

Uso:
    py -3 milpa_ai_backend/tools/gen_stress_md.py --out path.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

CONTENT = """# Manual MILPA — Prueba Markdown sintético

Este documento valida la extracción de TXT/MD preservando jerarquía y
paginación lógica. Marca canario h1: SAUCE_MD_INTRO_CANARIO_IJ5.

## 1. Cultivos asociados

La milpa combina maíz, frijol y calabaza. Marca canario h2:
TARANGA_MD_CULTIVOS_CANARIO_KL6.

- Maíz criollo: principal cultivo del sistema.
- Frijol negro: fijador de nitrógeno asociado.
- Calabaza pipiana: cobertura del suelo y semilla.

### 1.1 Beneficios documentados

1. Reducción de erosión por la cobertura.
2. Mejora de la fertilidad por fijación biológica.
3. Manejo integrado de plagas via diversidad funcional.

\f
# 2. Manejo agronómico

Marca canario página 2 (h1): CIPRES_MD_MANEJO_CANARIO_MN7.

## 2.1 Calendario

```text
Mes 1: preparación de cama de siembra.
Mes 2: siembra del maíz; tratamiento de semilla.
Mes 3: siembra del frijol y calabaza al pie del maíz.
```

## 2.2 Fertilización

Marca canario fertilización: FRESNO_MD_FERTILIZACION_CANARIO_OP8. La dosis se
ajusta al análisis de suelo y la etapa fenológica del cultivo dominante.

\f
# 3. Cosecha

Marca canario cosecha (h1 página 3): JACARANDA_MD_COSECHA_CANARIO_QR9.

- Maíz: tres a cinco meses según variedad.
- Frijol: 90 a 110 días.
- Calabaza: 90 días para fruto fresco; 120 para semilla seca.

Cierre del documento.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="milpa_ai_backend/data/stress_md_milpa.md",
        help="Ruta de salida",
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(CONTENT, encoding="utf-8")
    print(out.resolve())


if __name__ == "__main__":
    main()
