#!/usr/bin/env python
import sys
sys.path.insert(0, '/app')

from api.rag import get_retriever
from core.logic.rag_engine import insufficient_evidence

r = get_retriever()
query = "fertilizacion de maiz"
hits = r.hybrid(query, final_k=10)

print('Query:', query)
print('Total hits:', len(hits))
print('\nTop 10 RRF Scores:')
for i, h in enumerate(hits[:10]):
    score = h.get('rrf_score', 0.0)
    fid = h['fragment_id'][:12]
    print(f'  [{i+1}] {fid}... score={score:.6f}')

is_insuf, diag, filtered = insufficient_evidence(query, hits)

print(f'\nHits original: {len(hits)}')
print(f'Hits filtered (score >= 0.008): {len(filtered)}')
print(f'Insufficient?: {is_insuf}')
print(f'Reason: {diag.get("reason")}')
print(f'Diagnostics: {diag}')
