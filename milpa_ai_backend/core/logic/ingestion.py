# milpa_ai_backend/core/logic/ingestion.py
# Utilidades para persistir el archivo original y calcular el hash SHA-256.
# Ajuste clave: la función persist_original ahora devuelve SIEMPRE una ruta ABSOLUTA
# (p. ej., /app/data/documents/1234567890__archivo.ext) para que clamd (en otro
# contenedor) pueda acceder al archivo mediante el volumen compartido.

import time
import hashlib
import shutil
from pathlib import Path
from typing import Tuple, BinaryIO

from milpa_ai_backend.core.config import settings


def sha256_file(path: str) -> str:
    """
    Calcula el hash SHA-256 de un archivo sin cargarlo completo en memoria.
    Se lee en bloques para evitar consumo de memoria desmedido.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):  # bloques de ~1MB
            h.update(chunk)
    return h.hexdigest()


def _sanitize_filename(filename: str) -> str:
    """
    Canoniza el nombre de archivo para evitar rutas arbitrarias o caracteres
    problemáticos. Reemplaza separadores de ruta y trims simples.

    NOTA: No intentamos "limpiar" exhaustivamente (no se cambia el caso ni se
    tocan extensiones); solo se evita traversal y separadores.
    """
    safe = filename.replace("/", "_").replace("\\", "_").strip()
    # Evitar nombres vacíos o solo espacios
    return safe or f"upload_{int(time.time())}"


def persist_original(file_obj: BinaryIO, filename: str) -> Tuple[str, str]:
    """
    Persiste el archivo subido en data/documents con un nombre canonizado
    y retorna (ruta_absoluta_guardada, sha256).

    - Se antepone una marca de tiempo para evitar colisiones de nombre.
    - El hash se calcula sobre el archivo persistido para deduplicación posterior.
    - DEVUELVE RUTA ABSOLUTA (clave para escaneo AV por ruta compartida).
    """
    # 1) Resolver directorio de documentos a RUTA ABSOLUTA
    #    settings.DATA_DIR puede venir relativo (p. ej., "data/documents").
    #    .resolve() lo normaliza respecto al cwd del contenedor ("/app"),
    #    quedando típicamente "/app/data/documents".
    out_dir = Path(settings.DATA_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 2) Canonizar nombre (evitar rutas arbitrarias)
    safe_name = _sanitize_filename(filename)

    # 3) Prefijo temporal para unicidad (timestamp de segundos)
    ts = int(time.time())

    # 4) Construir ruta del archivo (ABSOLUTA)
    #    Importante: NO usamos rutas relativas; clamd escanea por ruta en SU FS,
    #    que comparte el volumen montado en /app/data con el contenedor 'ai'.
    out_path = (out_dir / f"{ts}__{safe_name}").resolve()

    # 5) Escribir a disco en streaming
    #    Copyfileobj consume el stream sin cargarlo completo en memoria.
    with open(out_path, "wb") as w:
        shutil.copyfileobj(file_obj, w)

    # 6) Calcular hash del archivo resultante (sobre la ruta ABSOLUTA)
    digest = sha256_file(str(out_path))

    # 7) Retornar ruta absoluta (str) + sha256
    return str(out_path), digest
