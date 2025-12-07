# milpa_ai_backend/core/config/__init__.py
# Módulo de configuración del backend

# Importar settings desde el módulo padre config.py
import sys
from pathlib import Path

# Agregar el directorio padre al path para poder importar config.py
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from config import settings

__all__ = ['settings']


