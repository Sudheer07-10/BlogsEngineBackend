import requests

url = "http://127.0.0.1:8000/api/discover"
payload = {
    "query": "AI in education",
    "vertical": "AI",
    "persona": {
        "personaName": "Alex",
        "personaRole": "GenZ Expert",
        "vibes": ["genz", "slang", "energetic"]
    }
}

print(f"Testing /api/discover with Persona: {payload['persona']['personaName']}")
try:
    resp = requests.post(url, json=payload, timeout=15)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        options = data.get("options", [])
        print(f"Found {len(options)} options.")
        for i, opt in enumerate(options):
            print(f"\nOption {i+1}:")
            print(f"Title: {opt['title']}")
            print(f"Summary: {opt['summary']}")
    else:
        print(f"Error: {resp.text}")
except Exception as e:
    print(f"Failed to connect: {e}")
