"""Pruebas RAG contra el PDF sintetico de cultivos."""
import json, urllib.request, textwrap, sys

BACKEND = "http://localhost:8000"
DOC_ID  = "da7c0b6d1c829b4cb8778f14a075c6476b6dfae3f6a7c20adb63a9e9453abd55"

QUERIES = [
    {
        "q": "Cual es la dosis de nitrogeno recomendada para maiz en suelo franco arenoso?",
        "expect": ["140", "franco arenoso", "kg/ha"],
    },
    {
        "q": "Que variedad de frijol tiene el mayor rendimiento y en que region se cultiva?",
        "expect": ["Peruano", "Sinaloa", "2,300"],
    },
    {
        "q": "Cuales son las principales plagas del maiz y como se controlan?",
        "expect": ["cogollero", "Spodoptera", "Bt"],
    },
    {
        "q": "Que especies de calabaza se cultivan en Mexico y cual se usa para pepitas?",
        "expect": ["argyrosperma", "pipiana", "pepita"],
    },
    {
        "q": "Cuanto nitrogeno necesita el chile habanero comparado con el guajillo?",
        "expect": ["200", "140", "habanero", "guajillo"],
    },
    {
        "q": "Cual es el pH optimo para el cultivo de tomate y que rendimiento se espera en invernadero?",
        "expect": ["5.8", "6.8", "150", "invernadero"],
    },
    {
        "q": "Que parametros indican un suelo con bajo contenido de fosforo segun el analisis Olsen?",
        "expect": ["10", "Olsen", "mg/kg"],
    },
    {
        "q": "Que rotaciones de cultivo se recomiendan para romper ciclos de plagas?",
        "expect": ["milpa", "leguminosa", "rotacion"],
    },
]

def query_rag(text: str) -> dict:
    payload = json.dumps({"query": text}).encode()
    req = urllib.request.Request(
        f"{BACKEND}/api/query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

sep = "=" * 80
total = len(QUERIES)
passed = 0

print(f"\n{sep}")
print(f"  PRUEBAS RAG - PDF SINTETICO DE CULTIVOS  ({total} consultas)")
print(f"{sep}\n")

for i, q in enumerate(QUERIES, 1):
    print(f"--- Pregunta {i}/{total} ---")
    print(f"Q: {q['q']}")

    try:
        result = query_rag(q["q"])
    except Exception as e:
        print(f"  ERROR: {e}\n")
        continue

    fragments = result.get("fragments", [])
    n_frags = len(fragments)

    # Check if any fragment comes from our document
    from_our_doc = [f for f in fragments if f.get("doc_id") == DOC_ID]

    # Combine text for keyword check
    all_text = " ".join(f.get("text", "") for f in fragments).lower()

    hits = []
    misses = []
    for kw in q["expect"]:
        if kw.lower() in all_text:
            hits.append(kw)
        else:
            misses.append(kw)

    score = len(hits) / len(q["expect"]) * 100 if q["expect"] else 100
    ok = score >= 50 and len(from_our_doc) > 0

    print(f"  Fragmentos devueltos: {n_frags}")
    print(f"  Del PDF sintetico:    {len(from_our_doc)}")
    if fragments:
        top = fragments[0]
        preview = top.get("text", "")[:150].replace("\n", " ")
        print(f"  Top score:            {top.get('score', 'N/A'):.4f}")
        print(f"  Top fragmento:        {preview}...")
        # Show entities from top fragment
        ents = top.get("entities", [])
        if ents:
            unique = set(f"{e['type']}:{e['value']}" for e in ents[:10])
            print(f"  Entidades NER:        {', '.join(sorted(unique)[:8])}")
    print(f"  Keywords encontrados: {hits}")
    if misses:
        print(f"  Keywords faltantes:   {misses}")
    print(f"  Cobertura:            {score:.0f}%  {'PASS' if ok else 'FAIL'}")
    print()

    if ok:
        passed += 1

print(f"{sep}")
print(f"  RESULTADO FINAL: {passed}/{total} consultas exitosas ({passed/total*100:.0f}%)")
print(f"{sep}")

if passed < total:
    print("\nNota: Con embeddings dummy, la busqueda semantica es limitada.")
    print("Los resultados mejoraran con el modelo real de sentence-transformers.")
