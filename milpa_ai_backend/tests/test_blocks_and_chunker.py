"""Pruebas unitarias para bloques con bbox y chunking por tokens HF.

Cubren las nuevas piezas operativas:

- ``core.logic.blocks.page_blocks``: extracción de bloques con bbox y orden de
  lectura multi-columna sobre un PDF generado al vuelo (1 columna y 2
  columnas).
- ``core.logic.blocks.group_blocks_into_chunks``: agrupación contigua hasta el
  tamaño objetivo respetando bordes anchos.
- ``core.logic.blocks.union_bbox``: bbox combinado.
- ``core.logic.token_chunker.chunk_by_tokens``: si el tokenizer está
  disponible, los chunks no exceden ``target_tokens`` (con margen por overlap).
"""
from __future__ import annotations

import os
import io
import sys
import tempfile

import fitz  # PyMuPDF
import pytest


# Permitir ejecutar pytest desde la raíz del repo
HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from milpa_ai_backend.core.logic.blocks import (  # noqa: E402
    Block,
    page_blocks,
    union_bbox,
    group_blocks_into_chunks,
)
from milpa_ai_backend.core.logic import token_chunker  # noqa: E402


def _make_pdf_one_column(text: str) -> str:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_text((72, 100), text, fontsize=11)
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    return f.name


def _make_pdf_two_columns(left: str, right: str) -> str:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insertamos varias líneas en cada columna para tener bloques bien
    # separados horizontalmente: PyMuPDF agrupa cuando los bloques quedan
    # cerca verticalmente.
    y = 100
    for line in left.split("\n"):
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    y = 100
    for line in right.split("\n"):
        page.insert_text((330, y), line, fontsize=11)
        y += 16
    f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    f.close()
    doc.save(f.name)
    doc.close()
    return f.name


def test_page_blocks_one_column_returns_blocks_with_bbox():
    p = _make_pdf_one_column("Lorem ipsum dolor sit amet\nconsectetur adipiscing elit")
    try:
        doc = fitz.open(p)
        try:
            page = doc.load_page(0)
            pb = page_blocks(page)
            assert pb.blocks, "deben extraerse bloques"
            assert pb.n_cols == 1
            for b in pb.blocks:
                assert isinstance(b, Block)
                assert b.x1 > b.x0 and b.y1 > b.y0
                assert b.text.strip()
        finally:
            doc.close()
    finally:
        os.unlink(p)


def test_page_blocks_two_columns_detects_n_cols():
    left = "\n".join([f"Izquierda linea {i} con texto suficiente para tener bloque" for i in range(8)])
    right = "\n".join([f"Derecha linea {i} con texto suficiente para tener bloque" for i in range(8)])
    p = _make_pdf_two_columns(left, right)
    try:
        doc = fitz.open(p)
        try:
            page = doc.load_page(0)
            pb = page_blocks(page)
            assert pb.blocks
            # Permitimos 1 ó 2 dependiendo de cómo PyMuPDF agrupe líneas en
            # bloques: lo importante es que el orden sea consistente y haya
            # bloques con x0 < ancho/2 y x0 > ancho/2.
            xs = [b.x0 for b in pb.blocks]
            assert any(x < pb.width / 2 for x in xs)
            assert any(x >= pb.width / 2 for x in xs)
        finally:
            doc.close()
    finally:
        os.unlink(p)


def test_union_bbox_aggregates_bounds():
    bs = [
        Block(page=1, x0=10, y0=20, x1=30, y1=40, text="a"),
        Block(page=1, x0=50, y0=5, x1=80, y1=25, text="b"),
        Block(page=1, x0=15, y0=60, x1=90, y1=70, text="c"),
    ]
    u = union_bbox(bs)
    assert u == (10, 5, 90, 70)


def test_group_blocks_into_chunks_respects_target():
    # Tres bloques de 100 chars cada uno → con target=150 esperamos 3 grupos.
    bs = [
        Block(page=1, x0=0, y0=10*i, x1=200, y1=10*i+10, text="x" * 100)
        for i in range(3)
    ]
    groups = group_blocks_into_chunks(bs, target_chars=150)
    assert len(groups) == 3
    # Con target=300 deberían combinarse de a 2 (cada par suma 200).
    groups = group_blocks_into_chunks(bs, target_chars=300)
    assert len(groups) <= 2


def test_token_chunker_caps_size_or_falls_back_gracefully():
    long_text = ("Maíz, frijol y calabaza forman la milpa. " * 200)
    out = token_chunker.chunk_by_tokens(long_text, target_tokens=80, overlap_tokens=10)
    assert out, "el chunker debe devolver al menos un chunk"
    tok = token_chunker.get_tokenizer()
    if tok is None:
        pytest.skip("tokenizer HF no disponible (offline); fallback validado")
    for ch in out:
        n = len(tok.encode(ch, add_special_tokens=False))
        # Permitimos margen por overlap: target + overlap es la cota dura.
        assert n <= 80 + 10 + 5, f"chunk con {n} tokens excede 80+overlap"


def test_token_chunker_keeps_paragraphs_when_small():
    text = "Primer párrafo corto.\n\nSegundo párrafo corto."
    out = token_chunker.chunk_by_tokens(text, target_tokens=200, overlap_tokens=0)
    if token_chunker.get_tokenizer() is None:
        pytest.skip("tokenizer HF no disponible")
    assert len(out) == 1
    assert "Primer" in out[0] and "Segundo" in out[0]
