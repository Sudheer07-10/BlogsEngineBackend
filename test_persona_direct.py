from summarizer import summarize

text = "The University of Texas at Arlington launched an AI webinar series to help educators."
persona = {
    "personaName": "Alex",
    "personaRole": "GenZ Expert",
    "vibes": ["genz", "slang", "energetic"]
}

print("Testing direct summarize with Persona...")
result = summarize(text, persona=persona)
print(f"Result: {result}")
