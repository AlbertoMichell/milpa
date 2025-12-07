import requests

url = "http://localhost:8000/api/query"
payload = {
    "query": "¿Cómo fertilizar maíz con nitrógeno?",
    "k": 3,
    "mode": "hybrid"
}

response = requests.post(url, json=payload)
print("Status:", response.status_code)

if response.status_code == 200:
    data = response.json()
    print("\n=== RESPUESTA ===")
    print("Modo:", data.get("answer_mode"))
    print("Citations:", len(data.get("citations", [])))
    print("\nRespuesta:")
    print(data.get("answer", "")[:800])
else:
    print("Error:", response.text)
