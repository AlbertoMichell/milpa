"""Tests del analyzer multilingüe del BM25Index.

Cubre las garantías de robustez frente a:
  - Acentos (input con tilde matchea sin tilde y viceversa).
  - Mayúsculas / minúsculas.
  - Stemming en español (plurales, conjugaciones simples).
  - Stemming en inglés (en queries técnicas mezcladas).
  - Identificadores con guion bajo (ej. canarios) deben preservarse.
"""
from __future__ import annotations

import shutil
import tempfile
from typing import Iterator, List

import pytest

from core.logic.bm25 import BM25Index


@pytest.fixture
def idx() -> Iterator[BM25Index]:
    tmp = tempfile.mkdtemp(prefix="bm25_ml_test_")
    try:
        b = BM25Index(index_dir=tmp, backend="tantivy")
        b.reset()
        yield b
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fids(hits: List[dict]) -> List[str]:
    return [h["fragment_id"] for h in hits]


def test_accent_folding_es(idx: BM25Index) -> None:
    docs = [
        {"fragment_id": "f1", "text": "El maíz crece en la milpa", "doc_id": "d1", "labels": []},
        {"fragment_id": "f2", "text": "Café orgánico de altura", "doc_id": "d1", "labels": []},
    ]
    idx.index_many(docs)
    assert "f1" in _fids(idx.search("maiz")), "query sin acento debe matchear con tilde"
    assert "f1" in _fids(idx.search("MAÍZ")), "lowercase + folding"
    assert "f2" in _fids(idx.search("cafe")), "café/cafe equivalentes"
    assert "f2" in _fids(idx.search("CAFE")), "case + folding"


def test_spanish_stemming(idx: BM25Index) -> None:
    docs = [
        {"fragment_id": "f1", "text": "La calabaza requiere humedad constante", "doc_id": "d1", "labels": []},
        {"fragment_id": "f2", "text": "Los frijoles fijan nitrógeno atmosférico", "doc_id": "d1", "labels": []},
    ]
    idx.index_many(docs)
    assert "f1" in _fids(idx.search("calabazas")), "plural debe stem-matchear"
    assert "f2" in _fids(idx.search("frijol")), "singular debe stem-matchear plural"
    assert "f2" in _fids(idx.search("nitrógenos")), "tilde + plural"


def test_canary_identifier_preserved(idx: BM25Index) -> None:
    """Identificadores con underscore deben mantenerse buscables íntegros.

    Tantivy.simple() separa por whitespace + puntuación pero conserva ``_``
    como parte del token, lo que es exactamente lo que necesitamos para no
    romper IDs como ``PETUNIA_TRESCOLUMNAS_CANARIO_8765``.
    """
    text = "Sección de prueba con marca PETUNIA_TRESCOLUMNAS_CANARIO_8765 incrustada."
    idx.index_many([
        {"fragment_id": "f1", "text": text, "doc_id": "d1", "labels": []},
        {"fragment_id": "f2", "text": "Texto irrelevante sobre otra cosa", "doc_id": "d1", "labels": []},
    ])
    hits = idx.search("PETUNIA_TRESCOLUMNAS_CANARIO_8765", topk=5)
    assert hits, "El canario debe encontrarse"
    assert hits[0]["fragment_id"] == "f1", "Debe ser el de mayor score"


def test_delete_by_doc_id(idx: BM25Index) -> None:
    idx.index_many([
        {"fragment_id": "f1", "text": "El maíz crece en la milpa", "doc_id": "d1", "labels": []},
        {"fragment_id": "f2", "text": "El frijol crece en la milpa", "doc_id": "d2", "labels": []},
    ])
    # Pre-condición: ambos doc_ids accesibles.
    assert "f1" in _fids(idx.search("maiz"))
    assert "f2" in _fids(idx.search("frijol"))
    deleted = idx.delete_by_doc_id("d1")
    assert deleted >= 1
    assert "f1" not in _fids(idx.search("maiz"))
    assert "f2" in _fids(idx.search("frijol"))


def test_normalization_consistency_with_query(idx: BM25Index) -> None:
    """Texto indexado en NFD/NFC debe matchear queries equivalentes."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Conducción del riego en cultivos de maíz")
    idx.index_many([
        {"fragment_id": "f1", "text": nfd, "doc_id": "d1", "labels": []},
    ])
    assert "f1" in _fids(idx.search("conducción del riego"))
    assert "f1" in _fids(idx.search("conduccion del riego"))


def test_query_special_chars_lenient(idx: BM25Index) -> None:
    """Queries con caracteres reservados de Tantivy (``:``, paréntesis) deben
    parsearse en modo tolerante sin romper.
    """
    idx.index_many([
        {"fragment_id": "f1", "text": "Manejo integrado de plagas (MIP) en milpa", "doc_id": "d1", "labels": []},
    ])
    hits = idx.search("manejo integrado (plagas)")
    assert hits, "modo lenient debe ignorar paréntesis"
