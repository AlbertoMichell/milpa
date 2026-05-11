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
    is_parcel_metric: bool = False
    metric: str | None = None
    normalized: str = ""


def normalize_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("¿", " ").replace("?", " ").replace("¡", " ").replace("!", " ")
    raw = re.sub(r"[^a-z0-9ñ%°\s\-_/.,]", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


_SHORT_VALID_QUERIES = {
    "ph", "p h", "npk", "n", "p", "k",
    "agua", "riego", "viento", "clima", "lluvia", "luz",
    "maiz", "maíz", "frijol", "chile", "tomate",
}

_DOMAIN_TERMS_RE = re.compile(
    r"\b(agua|humedad|riego|temperatura|viento|lluvia|precipitacion|clima|luz|ph|conductividad|"
    r"suelo|salinidad|cultivo|maiz|frijol|calabaza|tomate|chile|plaga|plagas|fertiliz|abono|"
    r"cosecha|historia|origen|biblioteca|manual|documento|nutriente|nitrogeno|fosforo|potasio)\b"
)


def _vowel_count(text: str) -> int:
    return len(re.findall(r"[aeiouáéíóú]", text, flags=re.IGNORECASE))


def _looks_like_keyboard_smash(norm: str) -> bool:
    if not norm:
        return True
    compact = re.sub(r"\s+", "", norm)
    if compact in _SHORT_VALID_QUERIES:
        return False
    if _DOMAIN_TERMS_RE.search(norm):
        return False
    if len(compact) >= 5 and _vowel_count(compact) == 0:
        return True
    if len(compact) >= 8:
        vowels = _vowel_count(compact)
        if vowels / max(len(compact), 1) < 0.18 and not _DOMAIN_TERMS_RE.search(norm):
            return True
    if re.search(r"^(.)\1{5,}$", compact, flags=re.IGNORECASE):
        return True
    if re.search(r"^(asdf|qwerty?|zxcv|xxxxx|aaaaa|dadad|abab|jaja{4,}|jeje{4,})", compact, flags=re.IGNORECASE):
        return True
    # Muchas consonantes seguidas sin formar términos agrícolas reconocibles.
    if re.search(r"[bcdfghjklmnpqrstvwxyzñ]{6,}", compact, flags=re.IGNORECASE):
        return True
    return False


def is_low_confidence(message: str) -> bool:
    raw = str(message or "").strip()
    norm = normalize_text(raw)
    if not norm:
        return True
    if norm in _SHORT_VALID_QUERIES:
        return False
    if _DOMAIN_TERMS_RE.search(norm):
        return False
    letters = len(re.findall(r"[a-záéíóúñ]", norm, flags=re.IGNORECASE))
    if letters / max(len(norm), 1) < 0.4:
        return True
    if len(norm) <= 3 and not re.search(r"\d", norm):
        return True
    return _looks_like_keyboard_smash(norm)


_LIBRARY_RE = re.compile(
    r"\b(historia|origen|origenes|domesticacion|domesticación|que\s+es|definicion|definición|"
    r"biblioteca|manual|documento|referencia|bibliograf|autor|fuente|cita|citas)\b"
)
_WATER_RE = re.compile(
    r"\b(agua|humedad\s+del\s+suelo|humedad\s+suelo|riego|riegos|regar|hidrico|hídrico|"
    r"como\s+estoy\s+de\s+agua|estoy\s+de\s+agua)\b"
)
_AIR_HUMIDITY_RE = re.compile(r"\b(humedad\s+(ambiental|relativa|del\s+aire|aire)|hr)\b")
_HARVEST_RE = re.compile(
    r"\b(cuando\s+(cosech|recolect)|fecha\s+de\s+cosech|proxima\s+cosech|"
    r"falta\s+para\s+cosech|cosecha\s+estimada)\b"
)
_PEST_RE = re.compile(r"\b(plaga|plagas|gusano|insecto|hongo|hongos|mildiu|tizon|roya|enfermedad)\b")
_FERT_RE = re.compile(r"\b(fertiliz|abono|nutri|nutricion|nitr[oó]geno|nitrogeno|fosforo|f[oó]sforo|potasio|npk)\b")
_TEMP_RE = re.compile(r"\b(temperatura|calor|frio|frío|helada|termico|térmico)\b")
_WIND_RE = re.compile(r"\b(viento|racha|rachas)\b")
_PRECIP_RE = re.compile(r"\b(lluvia|precipitacion|precipitación|llovio|llovió)\b")
_LIGHT_RE = re.compile(r"\b(luz|radiacion|radiación|solar|luminosidad)\b")
_CLIMATE_RE = re.compile(r"\b(clima|climatolog|meteorolog|condiciones\s+(climaticas|climáticas|ambientales))\b")
_SOIL_RE = re.compile(r"\b(suelo|ph|conductividad|salinidad|edafolog|materia\s+organica|materia\s+orgánica|textura)\b")
_STATUS_RE = re.compile(r"\b(estado|resumen|avance|progreso|salud|como\s+va|cómo\s+va|condicion|condición)\b")


def detect_intent(message: str) -> IntentResult:
    norm = normalize_text(message)

    # Consultas cortas pero válidas se clasifican antes del filtro de basura.
    if _AIR_HUMIDITY_RE.search(norm):
        return IntentResult(intent="air_humidity_status", is_parcel_metric=True, metric="air_humidity", normalized=norm)
    if _WATER_RE.search(norm) or norm == "humedad":
        return IntentResult(intent="water_balance", is_water=True, is_parcel_metric=True, metric="soil_moisture", normalized=norm)
    if _TEMP_RE.search(norm):
        return IntentResult(intent="temperature_status", is_parcel_metric=True, metric="air_temp", normalized=norm)
    if _WIND_RE.search(norm):
        return IntentResult(intent="wind_status", is_parcel_metric=True, metric="wind_speed", normalized=norm)
    if _PRECIP_RE.search(norm):
        return IntentResult(intent="precipitation_status", is_parcel_metric=True, metric="precipitation", normalized=norm)
    if _LIGHT_RE.search(norm):
        return IntentResult(intent="light_status", is_parcel_metric=True, metric="light", normalized=norm)
    if _CLIMATE_RE.search(norm):
        return IntentResult(intent="climate_status", is_parcel_metric=True, metric="climate", normalized=norm)
    if _SOIL_RE.search(norm):
        return IntentResult(intent="soil_condition", is_parcel_metric=True, metric="soil", normalized=norm)

    if is_low_confidence(message):
        return IntentResult(intent="garbage", is_garbage=True, normalized=norm)

    if _LIBRARY_RE.search(norm):
        return IntentResult(intent="library_question", is_library=True, normalized=norm)
    if _HARVEST_RE.search(norm):
        return IntentResult(intent="harvest_date", is_harvest=True, normalized=norm)
    if _PEST_RE.search(norm):
        return IntentResult(intent="pest_or_disease", normalized=norm)
    if _FERT_RE.search(norm):
        return IntentResult(intent="fertilization", normalized=norm)
    if _STATUS_RE.search(norm):
        return IntentResult(intent="crop_status", normalized=norm)
    return IntentResult(intent="unknown", normalized=norm)
