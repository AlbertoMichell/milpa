"""Smoke test del BM25Index multilingüe.

Verifica que:
  - El backend Tantivy se selecciona automáticamente.
  - Indexar y buscar funciona con acentos/folding/stemming.
  - delete_by_doc_id elimina fragmentos persistidos.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from milpa_ai_backend.core.logic.bm25 import BM25Index  # noqa: E402

CASES = [
    ("maíz", "fragment habla de maíz orgánico"),
    ("maiz", "Sin acento - debe matchear maíz orgánico"),
    ("MAIZ", "MAYUSCULAS sin acento - debe matchear"),
    ("calabazas", "Plural, debe stem-matchear con calabaza"),
    ("café", "Café variedad arábica de altura"),
    ("cafes", "Plural con stemming -> matchea cafés/café"),
    ("milpa", "Sistema de policultivo: milpa"),
    ("PETUNIA_TRESCOLUMNAS_CANARIO_8765", "Frase canaria con caracteres mixtos"),
]


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="bm25_test_")
    try:
        idx = BM25Index(index_dir=tmpdir, backend="tantivy")
        print("backend:", idx.backend)
        idx.reset()
        # Indexamos varios documentos para validar matching.
        docs = [
            {
                "fragment_id": f"f-{i}",
                "text": text,
                "doc_id": "doc-1",
                "labels": ["es"],
                "entities": [],
            }
            for i, text in enumerate([
                "El maíz crece en la milpa con frijol y calabaza.",
                "Las calabazas hacen sombra y conservan humedad.",
                "Café orgánico de altura, secado al sol.",
                "PETUNIA_TRESCOLUMNAS_CANARIO_8765 marca la sección triple-columna.",
                "Sistema agrícola tradicional mesoamericano",
            ])
        ]
        idx.index_many(docs)

        print("\n--- queries ---")
        for q, label in CASES:
            hits = idx.search(q, topk=3)
            print(f"  q='{q}' ({label}) -> {len(hits)} hits")
            for h in hits[:2]:
                print(f"      score={h['score']:.3f} fid={h['fragment_id']}")

        print("\n--- delete_by_doc_id ---")
        deleted = idx.delete_by_doc_id("doc-1")
        print("  removed:", deleted)
        post_hits = idx.search("maiz", topk=5)
        print("  post-delete hits para 'maiz':", len(post_hits))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
