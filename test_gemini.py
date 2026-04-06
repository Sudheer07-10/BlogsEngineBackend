import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("No Gemini API Key found.")
else:
    client = genai.Client(api_key=api_key)
    try:
        # Try to list models or just try 1.5 flash
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents="Hello",
        )
        print("Model gemini-1.5-flash is working.")
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents="Hello",
            )
            print("Model gemini-2.5-flash is working.")
        except Exception as e:
            print(f"Model gemini-2.5-flash failed: {e}")
            
    except Exception as e:
        print(f"Gemini check failed: {e}")
