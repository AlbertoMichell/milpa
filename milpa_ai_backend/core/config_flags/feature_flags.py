# milpa_ai_backend/core/config/feature_flags.py
# Sistema de feature flags dinámico basado en BD.
# SPRINT 20: Reemplaza variables de entorno estáticas.

import sqlite3
import json
from typing import Any, Optional
from pathlib import Path

from milpa_ai_backend.core.config import settings


class FeatureFlags:
    """
    Gestor de feature flags dinámicos almacenados en BD.
    Permite cambiar configuración sin reiniciar servicios.
    """
    
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.SQLITE_PATH
        self._cache: dict[str, dict] = {}
        self._load_flags()
    
    def _load_flags(self):
        """Carga todos los flags desde BD al caché."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT flag_name, enabled, config_json
                FROM feature_flags
            """)
            
            for row in cursor.fetchall():
                flag_name, enabled, config_json = row
                self._cache[flag_name] = {
                    "enabled": bool(enabled),
                    "config": json.loads(config_json) if config_json else {}
                }
            
            conn.close()
        except Exception as e:
            print(f"Warning: Could not load feature flags from DB: {e}")
    
    def is_enabled(self, flag_name: str, default: bool = False) -> bool:
        """
        Verifica si un flag está habilitado.
        
        Args:
            flag_name: Nombre del flag
            default: Valor por defecto si no existe
        
        Returns:
            True si el flag está enabled=1
        """
        if flag_name not in self._cache:
            return default
        
        return self._cache[flag_name]["enabled"]
    
    def get_config(self, flag_name: str, key: Optional[str] = None, default: Any = None) -> Any:
        """
        Obtiene configuración JSON de un flag.
        
        Args:
            flag_name: Nombre del flag
            key: Clave específica del JSON (opcional)
            default: Valor por defecto
        
        Returns:
            Configuración completa o valor de la clave
        
        Ejemplos:
            >>> flags.get_config("EMBEDDINGS_MODEL", "model")
            "BAAI/bge-m3"
            
            >>> flags.get_config("RAG_MODE")
            {"mode": "hybrid", "bm25_weight": 0.4, "vector_weight": 0.6}
        """
        if flag_name not in self._cache:
            return default
        
        config = self._cache[flag_name]["config"]
        
        if key is None:
            return config
        
        return config.get(key, default)
    
    def reload(self):
        """Recarga flags desde BD (útil para cambios en caliente)."""
        self._cache.clear()
        self._load_flags()
    
    def set_flag(self, flag_name: str, enabled: bool, config: Optional[dict] = None):
        """
        Actualiza un flag en BD y caché.
        
        Args:
            flag_name: Nombre del flag
            enabled: True para habilitar, False para deshabilitar
            config: Configuración JSON (opcional)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE feature_flags
                SET enabled = ?, config_json = ?, updated_at = datetime('now')
                WHERE flag_name = ?
            """, (
                int(enabled),
                json.dumps(config) if config else None,
                flag_name
            ))
            
            conn.commit()
            conn.close()
            
            # Actualizar caché
            self._cache[flag_name] = {
                "enabled": enabled,
                "config": config or {}
            }
            
        except Exception as e:
            print(f"Error updating feature flag {flag_name}: {e}")


# ────────────────────────────────────────────────────────────────
# INSTANCIA GLOBAL (singleton)
# ────────────────────────────────────────────────────────────────

feature_flags = FeatureFlags()


# ────────────────────────────────────────────────────────────────
# HELPERS PARA ACCESO RÁPIDO
# ────────────────────────────────────────────────────────────────

def is_reranker_enabled() -> bool:
    """Shortcut: verifica si reranker está habilitado."""
    return feature_flags.is_enabled("RERANKER_ENABLED", default=False)


def get_embeddings_model() -> str:
    """Obtiene modelo de embeddings configurado."""
    return feature_flags.get_config("EMBEDDINGS_MODEL", "model", default="BAAI/bge-m3")


def get_rag_mode() -> dict:
    """Obtiene configuración completa de modo RAG."""
    return feature_flags.get_config("RAG_MODE", default={
        "mode": "hybrid",
        "bm25_weight": 0.4,
        "vector_weight": 0.6
    })


def is_blue_green_v2_enabled() -> tuple[bool, int]:
    """
    Verifica si UI v2 (blue-green) está habilitada.
    
    Returns:
        (enabled, rollout_percent): Tupla con flag y % de rollout
    """
    enabled = feature_flags.is_enabled("BLUE_GREEN_V2_ENABLED", default=False)
    rollout = feature_flags.get_config("BLUE_GREEN_V2_ENABLED", "rollout_percent", default=0)
    return enabled, rollout
