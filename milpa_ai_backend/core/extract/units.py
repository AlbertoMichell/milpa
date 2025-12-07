# milpa_ai_backend/core/extract/units.py
# Detección y normalización básica de magnitudes con pint.
# - Busca patrones "número + unidad" (incluye decimales y separadores).
# - Intenta normalizar a SI con pint (si no puede, lo omite de forma segura).

from __future__ import annotations
import regex as re
from typing import List, Dict, Any
from pint import UnitRegistry

ureg = UnitRegistry(auto_reduce_dimensions=True)
Q_ = ureg.Quantity

# Unidades comunes y alias rápidos (añade/ajusta las que necesites)
ALIASES = {
    "km/h": "kilometer / hour",
    "kmh": "kilometer / hour",
    "m/s": "meter / second",
    "kph": "kilometer / hour",
    "°c": "degC",
    "°f": "degF",
}

UNIT_RX = re.compile(
    r"""
    (?P<value>[-+]?\d+(?:[.,]\d+)?)      # número
    \s*
    (?P<unit>
        [a-zA-Zµ°/%]+(?:[/\.\-][a-zA-Z]+)*   # unidad básica con separadores típicos
    )
    """,
    re.VERBOSE,
)

def _canonical(u: str) -> str:
    u = u.strip().lower()
    return ALIASES.get(u, u)

def extract_units(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not text:
        return out
    for m in UNIT_RX.finditer(text):
        raw_v = m.group("value").replace(",", ".")
        raw_u = _canonical(m.group("unit"))
        try:
            q = Q_(float(raw_v), raw_u)
            si = q.to_base_units()
            out.append(
                {
                    "value": float(raw_v),
                    "unit": raw_u,
                    "value_si": si.magnitude,
                    "unit_si": f"{si.units:~P}",
                }
            )
        except Exception:
            # No parseable -> lo ignoramos
            continue
    return out
