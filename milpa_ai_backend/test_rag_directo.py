#!/usr/bin/env python3
"""Test RAG directo sin pytest"""

import sys
sys.path.insert(0, '.')

from milpa_ai_backend.core.logic.bm25 import BM25Index
from milpa_ai_backend.core.logic.vectordb import VectorStore
from milpa_ai_backend.core.logic.embeddings import EmbeddingModel
from milpa_ai_backend.core.logic.rag_engine import HybridRetriever
import sqlite3

# Cargar fragmentos
conn = sqlite3.connect('data/main.db')
cur = conn.cursor()
cur.execute("SELECT f.fragment_id, f.text, f.doc_id, d.source FROM fragments f LEFT JOIN docs d ON f.doc_id = d.doc_id")
rows = cur.fetchall()
conn.close()

print(f"Fragmentos en BD: {len(rows)}")
for fid, text, did, src in rows:
    print(f"  {fid[:8]}... | {text[:60]}...")

# Crear índices
bm25 = BM25Index(backend='memory')
vs = VectorStore(path='/tmp/test_vs', collection='test')
emb = EmbeddingModel()

docs_bm25 = []
texts = []
ids = []
metas = []

for fid, text, did, src in rows:
    if not text:
        continue
    docs_bm25.append({"fragment_id": fid, "text": text, "labels": [], "doc_id": did or "", "entities": []})
    texts.append(text)
    ids.append(fid)
    metas.append({"fragment_id": fid, "doc_id": did or "", "source": src or ""})

bm25.index_many(docs_bm25)
embeddings = emb.embed_texts(texts)
vs.add(ids=ids, embeddings=embeddings, metadatas=metas)

print(f"\nIndexados: BM25={len(docs_bm25)}, Vector={len(ids)}")

# Crear retriever
retriever = HybridRetriever(vector_store=vs, bm25_index=bm25, embedder=emb)

# Query
query = "nutrientes esenciales maíz"
results = retriever.query(query, k=8, mode="hybrid", labels_filter=None)

print(f"\nQuery: '{query}'")
print(f"Resultados: {len(results)}")
for r in results:
    print(f"  Score: {r['rrf_score']:.4f} | {r['text'][:80]}...")
