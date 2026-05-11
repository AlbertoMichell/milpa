# milpa_ai_backend/main.py
# Punto de entrada de la app FastAPI (uvicorn lo importa como "app").
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from milpa_ai_backend.api.server import build_app

# Exponer la instancia de FastAPI como "app"
# para compatibilidad directa con uvicorn/gunicorn.
app = build_app()
