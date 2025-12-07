# milpa_ai_backend/core/security/av.py
# Cliente AV robusto para ClamAV (clamd). Hace doble verificación:
# 1) Escaneo por ruta (SCAN).
# 2) Escaneo por streaming (INSTREAM).
# Si cualquiera marca FOUND → se bloquea la carga.
#
# Motivo: en entornos docker es común que clamd no pueda validar rutas
# (montajes/ro, path-check, etc.). INSTREAM evita ese problema.

from __future__ import annotations

import io
import os
from typing import Tuple, Optional

import clamd
from milpa_ai_backend.core.config import settings


class AntivirusError(Exception):
    """Errores del escáner AV."""


def _connect_clamd() -> Optional[clamd.ClamdNetworkSocket]:
    """
    Conecta a clamd por TCP. Intenta ping/version para asegurar disponibilidad.
    Lanza AntivirusError si no conecta y AV_OPTIONAL es False.
    Retorna None si AV_OPTIONAL=True y no puede conectar.
    """
    host = settings.CLAMAV_HOST
    port = settings.CLAMAV_PORT
    try:
        cd = clamd.ClamdNetworkSocket(host=host, port=port)
        # Validación liviana del daemon
        try:
            pong = cd.ping()
            if pong != "PONG":
                # Algunos builds pueden no responder correctamente a ping; probamos version
                _ = cd.version()
        except Exception:
            # Si falla ping, probamos version; si también falla, error
            _ = cd.version()
        return cd
    except Exception as e:
        if settings.AV_OPTIONAL:
            # Dev/staging: permitimos continuar sin AV
            return None
        raise AntivirusError(f"No se pudo contactar con ClamAV: {e}")


def _parse_scan_result(result: Optional[dict]) -> Tuple[str, Optional[str]]:
    """
    Normaliza la respuesta de clamd:
    - SCAN → {"/ruta/archivo": ("OK"|"FOUND","NombreFirma")}
    - INSTREAM → {"stream": ("OK"|"FOUND","NombreFirma")}
    Retorna: (status, signature) con status en {"OK","FOUND","UNKNOWN"}
    """
    if not result or not isinstance(result, dict):
        return "UNKNOWN", None
    # Tomar el primer item
    key, val = next(iter(result.items()))
    if not isinstance(val, (tuple, list)) or len(val) < 1:
        return "UNKNOWN", None
    status = val[0]
    sig = val[1] if len(val) > 1 else None
    if status not in ("OK", "FOUND"):
        return "UNKNOWN", sig
    return status, sig


def _instream_file(cd: clamd.ClamdNetworkSocket, path: str) -> Tuple[str, Optional[str]]:
    """
    Escanea el archivo vía INSTREAM abriéndolo y enviándolo en streaming a clamd.
    """
    # python-clamd gestiona el protocolo INSTREAM y chunking interno.
    with open(path, "rb") as fh:
        res = cd.instream(fh)
    return _parse_scan_result(res)


def _scan_path(cd: clamd.ClamdNetworkSocket, path: str) -> Tuple[str, Optional[str]]:
    """
    Escaneo por ruta absoluta. Puede fallar en docker si clamd no puede acceder
    (path-check o montajes). Por eso es complementario a INSTREAM.
    """
    try:
        res = cd.scan(path)
    except Exception:
        # Si SCAN falla (permiso, path-check, etc.), tratamos como UNKNOWN
        return "UNKNOWN", None
    return _parse_scan_result(res)


def scan_file_strict(path: str) -> None:
    """
    Realiza SCAN por ruta y luego INSTREAM. Si cualquiera detecta malware → lanza.
    Si ambos quedan en UNKNOWN y AV_OPTIONAL=False → lanza (política estricta).
    Si AV_OPTIONAL=True y ClamAV no está disponible, retorna sin error.
    """
    # Asegurar ruta absoluta (clamd suele ser más estricto con paths relativos)
    abs_path = os.path.abspath(path)

    # Conectamos al daemon (puede retornar None si AV_OPTIONAL=True)
    cd = _connect_clamd()
    
    # Si no hay conexión y AV_OPTIONAL=True, omitir escaneo
    if cd is None:
        return

    # 1) Intento por ruta
    status_path, sig_path = _scan_path(cd, abs_path)
    if status_path == "FOUND":
        raise AntivirusError(f"Malware detectado (SCAN): {sig_path}")

    # 2) Intento por streaming (independiente del filesystem del daemon)
    try:
        status_stream, sig_stream = _instream_file(cd, abs_path)
    except Exception as e:
        status_stream, sig_stream = "UNKNOWN", None
        # Si INSTREAM falla por algún motivo y tenemos AV_OPTIONAL=False,
        # caeremos en la política estricta más abajo.
    if status_stream == "FOUND":
        raise AntivirusError(f"Malware detectado (INSTREAM): {sig_stream}")

    # Política: si ambos son UNKNOWN → decidir según AV_OPTIONAL
    if status_path == "UNKNOWN" and status_stream == "UNKNOWN":
        if settings.AV_OPTIONAL:
            # Continuamos sin error
            return
        raise AntivirusError("ClamAV no devolvió resultado (SCAN/INSTREAM=UNKNOWN)")
    # Si llegamos aquí, ambos fueron OK (o SCAN=UNKNOWN pero INSTREAM=OK).
    return
