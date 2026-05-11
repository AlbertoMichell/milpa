from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass
class IntentResult:
    intent: str
    is_garbage: bool = False
    is_library: bool = False
    is_water: bool = False
    is_harvest: bool = False
    normalized: str = ""


def normalize_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = re.sub(r"\s+", " ", raw)
    return raw


def is_low_confidence(message: str) -> bool:
    raw = str(message or "").strip()
    if not raw:
        return True
    letters = len(re.findall(r"[a-zA-Z]", raw))
    if letters / max(len(raw), 1) < 0.4:
        return True
    if re.search(r"^(.)\1{5,}$", raw, flags=re.IGNORECASE):
        return True
    if re.search(r"^(dadad|abab|asdf|qwert|xxxxx)", raw, flags=re.IGNORECASE):
        return True
    if len(raw) <= 3 and not re.search(r"\d", raw):
        return True
    return False


_WATER_RE = re.compile(
    r"\b(agua|humedad(\s+(del\s+)?suelo)?|riego(s)?|regar|como\s+estoy\s+de\s+agua|estoy\s+de\s+agua)\b"
)
_HARVEST_RE = re.compile(
    r"\b(cuando\s+(cosech|recolect)|fecha\s+de\s+cosech|proxima\s+cosech|falta\s+para\s+cosech)\b"
)
_LIBRARY_RE = re.compile(
    r"\b(historia|origen|que\s+es|definicion|biblioteca|manual|documento|referencia|bibliograf)\b"
)
_PEST_RE = re.compile(
    r"\b(plaga|plagas|gusano|insecto|hongo|hongos|mildiu|tizon|roya|enfermedad)\b"
)
_FERT_RE = re.compile(r"\b(fertiliz|abono|nutri|nutricion)\b")
_CLIMATE_RE = re.compile(
    r"\b(clima|lluvia|precipitacion|viento|temperatura|calor|frio|helada|sequia)\b"
)
_SOIL_RE = re.compile(r"\b(suelo|ph|conductividad|salinidad|edafolog|nutrientes)\b")
_STATUS_RE = re.compile(r"\b(estado|resumen|avance|progreso|salud|como\s+va)\b")


def detect_intent(message: str) -> IntentResult:
    norm = normalize_text(message)
    if is_low_confidence(message):
        return IntentResult(intent="garbage", is_garbage=True, normalized=norm)
    if _LIBRARY_RE.search(norm):
        return IntentResult(intent="library_question", is_library=True, normalized=norm)
    if _WATER_RE.search(norm):
        return IntentResult(intent="water_balance", is_water=True, normalized=norm)
    if _HARVEST_RE.search(norm):
        return IntentResult(intent="harvest_date", is_harvest=True, normalized=norm)
    if _PEST_RE.search(norm):
        return IntentResult(intent="pest_or_disease", normalized=norm)
    if _FERT_RE.search(norm):
        return IntentResult(intent="fertilization", normalized=norm)
    if _CLIMATE_RE.search(norm):
        return IntentResult(intent="climate_risk", normalized=norm)
    if _SOIL_RE.search(norm):
        return IntentResult(intent="soil_condition", normalized=norm)
    if _STATUS_RE.search(norm):
        return IntentResult(intent="crop_status", normalized=norm)
    return IntentResult(intent="unknown", normalized=norm)
