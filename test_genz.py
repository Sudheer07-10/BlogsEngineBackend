from summarizer import summarize
import os
from config import Config

def test_genz_summary():
    print("[Test] Testing Gen-Z Summary (Default)...")
    
    text = """
    A new study suggests that regular exercise can significantly improve mental health and cognitive function. 
    Researchers followed 5,000 participants over ten years and found that those who exercised at least 
    three times a week had a 30% lower risk of developing moderate-to-severe anxiety and depression.
    The study emphasized that even light activities like walking or gardening showed positive results.
    """
    
    # Test with None (should trigger default Alex/Gen-Z)
    result = summarize(text, persona=None)
    print("\n--- Result with persona=None (Gen-Z Default) ---")
    print(result)
    
    # Validate result format
    if "|" in result:
        parts = result.split("|")
        print(f"\n[OK] Format check passed: {len(parts)} segments found.")
        
        # Check for persona presence (Alex / Slang)
        slang_terms = ["no cap", "Alex", "lit", "fr"]
        found = False
        for term in slang_terms:
            if term.lower() in result.lower():
                print(f"[OK] Persona check passed: Found '{term}' in output.")
                found = True
        
        if not found:
            print("[Error] Error: Gen-Z persona elements missing from default output.")
    else:
        print("[Error] Error: Result format invalid (no '|' separator).")

if __name__ == "__main__":
    test_genz_summary()
