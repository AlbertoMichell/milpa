# milpa_ai_backend/tests/conftest.py
# ------------------------------------------------------------------
# Configura entorno de pruebas para que NUNCA escriba en el árbol del código:
# - Defaults seguros a /tmp cuando las variables de entorno no vienen dadas.
# - Crea SOLO subcarpetas dentro de /tmp (evita PermissionError en /app).
# - Mueve el caché de pytest fuera del repo (evita warnings/errores de permisos).
# - Provee fixtures comunes: fragmentos sintéticos, índice BM25 y VectorStore.
# ------------------------------------------------------------------
import os
import json
import shutil
import random
import string
from pathlib import Path
import pytest

# ===============================
# Rutas base y defaults seguros
# ===============================
BASE_DIR = Path(__file__).resolve().parents[1]  # .../milpa_ai_backend
SAFE_TMP = Path(os.environ.get("TMPDIR", "/tmp"))

# Taxonomía y modelos (por defecto, la carpeta del repo dentro del contenedor)
os.environ.setdefault("TAXONOMY_VERSION", "2025.09.10")
os.environ.setdefault("MODELS_DIR", str(BASE_DIR / "models"))

# IMPORTANTÍSIMO: forzar defaults a /tmp para artefactos de pruebas
os.environ.setdefault("CHROMA_DIR", str(SAFE_TMP / "vector_db_test"))
os.environ.setdefault("SQLITE_PATH", str(SAFE_TMP / "milpa_knowledge_test.db"))
os.environ.setdefault("DATA_DIR", str(SAFE_TMP / "data"))
os.environ.setdefault("BM25_INDEX_DIR", str(SAFE_TMP / "bm25_idx"))
os.environ.setdefault("BM25_BACKEND", "memory")  # fuerza backend BM25 en memoria para tests estables

# Crear SOLO directorios bajo /tmp (o donde apunten las envs sobre /tmp)
Path(os.environ["CHROMA_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["BM25_INDEX_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["SQLITE_PATH"]).parent.mkdir(parents=True, exist_ok=True)

# PyTest cache fuera del repo para evitar permisos en /app
if "PYTEST_CACHE_DIR" not in os.environ:
    cache_dir = SAFE_TMP / "pytest_cache"
    os.environ["PYTEST_CACHE_DIR"] = str(cache_dir)
    # Inyecta opción para que pytest respete ese directorio de cache
    os.environ["PYTEST_ADDOPTS"] = (
        os.environ.get("PYTEST_ADDOPTS", "") + f" -o cache_dir={cache_dir}"
    ).strip()
    cache_dir.mkdir(parents=True, exist_ok=True)

# ==========================================================
# Limpieza de VectorDB de tests al inicio de la sesión
# ==========================================================
@pytest.fixture(scope="session", autouse=True)
def _cleanup_vector_db_session():
    """
    Garantiza que el directorio del índice vectorial de PRUEBAS esté limpio
    al comenzar la sesión de tests. No toca índices de producción.
    """
    vec_dir = os.environ["CHROMA_DIR"]
    if os.path.exists(vec_dir):
        shutil.rmtree(vec_dir, ignore_errors=True)
    os.makedirs(vec_dir, exist_ok=True)
    yield
    # Si deseas limpiar al final, descomenta:
    # shutil.rmtree(vec_dir, ignore_errors=True)

# ======================
# Utilidades de pruebas
# ======================
def _rand_id(prefix="frag"):
    return prefix + "_" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))

# ======================
# Fixtures de contenido
# ======================
@pytest.fixture(scope="session")
def sample_fragments():
    """
    Devuelve 10 fragmentos sintéticos ya en ES, cubriendo:
    - CULTIVOS: maiz, trigo
    - PLAGAS: roya, gusano cogollero
    - NUTRIENTES: N, P (y K en uno de contexto)
    - FENOFASE: macollaje, floracion
    - LUGAR: puebla, oaxaca
    Mezcla RECOMENDACION/DATO/RESULTADO y algunos neutros para 'insuficiencia'.
    """
    data = [
        # Maíz recomendaciones
        ("Se recomienda fertilización con N en maiz durante macollaje en Puebla.",
         "doc_maiz_1", ["RECOMENDACION"],
         [{"type": "CULTIVO", "value": "maiz"},
          {"type": "NUTRIENTE", "value": "N"},
          {"type": "FENOFASE", "value": "macollaje"},
          {"type": "LUGAR", "value": "puebla"}]),

        ("Para maiz con presencia de gusano cogollero, aplicar control integrado.",
         "doc_maiz_1", ["RECOMENDACION"],
         [{"type": "CULTIVO", "value": "maiz"},
          {"type": "PLAGA", "value": "gusano cogollero"}]),

        ("Datos de rendimiento promedio en maiz bajo riego, tabla 2.",
         "doc_maiz_1", ["DATO"],
         [{"type": "CULTIVO", "value": "maiz"}]),

        # Trigo
        ("La roya afecta al trigo en floracion; monitorear síntomas.",
         "doc_trigo_1", ["RESULTADO", "DATO"],
         [{"type": "PLAGA", "value": "roya"},
          {"type": "CULTIVO", "value": "trigo"},
          {"type": "FENOFASE", "value": "floracion"}]),

        ("Se recomienda manejo de N y P en trigo para maximizar rendimiento.",
         "doc_trigo_1", ["RECOMENDACION"],
         [{"type": "NUTRIENTE", "value": "N"},
          {"type": "NUTRIENTE", "value": "P"},
          {"type": "CULTIVO", "value": "trigo"}]),

        # Mixtos / ruido controlado
        ("Promedio regional en Oaxaca para maiz de temporal.",
         "doc_mix_1", ["DATO"],
         [{"type": "LUGAR", "value": "oaxaca"},
          {"type": "CULTIVO", "value": "maiz"}]),

        ("El minador se detectó en ensayos con tomate; comparar con maiz.",
         "doc_mix_1", ["RESULTADO"],
         [{"type": "PLAGA", "value": "minador"}]),

        ("La fertilización foliar puede apoyar en etapas tempranas.",
         "doc_mix_1", [], []),

        ("Muestreo de suelo recomendado antes de la siembra.",
         "doc_mix_1", ["RECOMENDACION"], []),

        ("Valores de P y K en suelos franco-arcillosos.",
         "doc_mix_1", ["DATO"],
         [{"type": "NUTRIENTE", "value": "P"},
          {"type": "NUTRIENTE", "value": "K"}]),
    ]

    frags = []
    for text, doc_id, labels, ents in data:
        frags.append({
            "fragment_id": _rand_id("frag"),
            "doc_id": doc_id,
            "text_es": text,
            "labels": labels,
            "entities": ents,
        })
    return frags

# ======================
# Fixtures de infraestructura
# ======================
@pytest.fixture
def bm25_index(tmp_path):
    """
    Devuelve un índice BM25 vacío en un directorio temporal (bajo /tmp).
    No pisa índices reales y permite reset entre tests.
    CRÍTICO: pasamos backend='memory' explícitamente para asegurar estabilidad.
    """
    from core.logic.bm25 import BM25Index
    idx_dir = tmp_path / "bm25"
    # Forzar backend memory para evitar incompatibilidades de Tantivy en tests
    idx = BM25Index(index_dir=str(idx_dir), backend='memory')
    idx.reset()
    return idx

@pytest.fixture
def embedder():
    """
    Carga el modelo de embeddings (si no está disponible en el contenedor,
    el test se marca como 'skipped' en lugar de fallar).
    """
    import pytest as _pytest
    try:
        from core.logic.embeddings import EmbeddingModel
    except Exception as e:
        _pytest.skip(f"Embeddings no disponibles: {e}")
    return EmbeddingModel()

@pytest.fixture
def vector_store():
    """
    Crea un VectorStore de pruebas, usando el CHROMA_DIR que forzamos a /tmp.
    Si Chroma no está instalado/operativo, se 'skippea' el test.
    """
    import pytest as _pytest
    try:
        from core.logic.vectordb import VectorStore
    except Exception as e:
        _pytest.skip(f"Chroma no disponible: {e}")
    # Pasa la ruta explícitamente para evitar depender de defaults internos
    return VectorStore(path=os.environ["CHROMA_DIR"], collection="milpa_test")

# ======================
# Fixtures de Base de Datos (para tests de contrato)
# ======================
@pytest.fixture(scope="session")
def test_db_path():
    """Ruta temporal para BD de tests."""
    db_path = SAFE_TMP / "test_milpa.db"
    # Limpiar si existe de sesión anterior
    if db_path.exists():
        db_path.unlink()
    return str(db_path)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database(test_db_path):
    """
    Aplica migraciones al schema de BD de tests al inicio de la sesión.
    Esto crea las tablas necesarias (docs, fragments, feature_flags, etc).
    """
    import sqlite3
    from pathlib import Path
    
    # Crear BD vacía
    conn = sqlite3.connect(test_db_path)
    conn.close()
    
    # Aplicar migraciones SQL directamente
    migrations_dir = BASE_DIR / "core" / "logic" / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))
    
    conn = sqlite3.connect(test_db_path)
    cur = conn.cursor()
    
    for sql_file in sql_files:
        with open(sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
            # Filtrar líneas que comienzan con # (comentarios no-SQL)
            lines = []
            for line in sql.split('\n'):
                stripped = line.strip()
                # Ignorar líneas vacías y comentarios con #
                if not stripped.startswith('#'):
                    lines.append(line)
            sql_clean = '\n'.join(lines)
            # Ejecutar múltiples statements
            if sql_clean.strip():
                cur.executescript(sql_clean)
    
    conn.commit()
    conn.close()
    
    # Configurar env var para que la app use esta BD
    original_db = os.environ.get("SQLITE_PATH")
    os.environ["SQLITE_PATH"] = test_db_path
    
    yield
    
    # Restaurar env var original
    if original_db:
        os.environ["SQLITE_PATH"] = original_db
    else:
        os.environ.pop("SQLITE_PATH", None)
