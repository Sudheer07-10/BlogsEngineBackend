"""
summarizer.py — Extractive text summarizer using TF-IDF scoring.
No external APIs or keys required.
"""

import math
import re
from collections import Counter
import os
from google import genai
from google.genai import types
from config import Config
import time


# Common English stop words to ignore in scoring
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "i", "you", "he", "she", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "what", "which", "who", "whom", "where", "when", "how", "why", "not",
    "no", "nor", "so", "if", "then", "than", "too", "very", "just", "about",
    "above", "after", "again", "all", "also", "am", "as", "because",
    "before", "between", "both", "during", "each", "few", "get", "got",
    "into", "more", "most", "much", "must", "new", "now", "old", "only",
    "other", "out", "over", "own", "same", "some", "such", "up", "down",
    "here", "there", "through", "under", "upon", "while", "said", "says",
}


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    # Split on period, exclamation, question mark followed by space or end
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter out very short fragments
    return [s.strip() for s in raw if len(s.strip()) > 10]


def _tokenize(text: str) -> list[str]:
    """Convert text to lowercase word tokens, removing stop words."""
    words = re.findall(r'\b[a-z]{2,}\b', text.lower())
    return [w for w in words if w not in STOP_WORDS]


def _compute_tf(words: list[str]) -> dict[str, float]:
    """Compute term frequency for a list of words."""
    counts = Counter(words)
    total = len(words)
    if total == 0:
        return {}
    return {word: count / total for word, count in counts.items()}


def _compute_idf(sentences_words: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency across sentences."""
    n = len(sentences_words)
    if n == 0:
        return {}
    
    doc_freq: dict[str, int] = Counter()
    for words in sentences_words:
        unique_words = set(words)
        for w in unique_words:
            doc_freq[w] += 1

    return {word: math.log(n / (1 + freq)) for word, freq in doc_freq.items()}


def _fallback_summarize(text: str, max_sentences: int = 3, persona: dict = None) -> str:
    """TF-IDF fallback with basic persona stylistic injection."""
    if not text or not text.strip():
        return ""

    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        summary = " ".join(sentences)
    else:
        sentences_words = [_tokenize(s) for s in sentences]
        idf = _compute_idf(sentences_words)
        scores = []
        for idx, (sentence, words) in enumerate(zip(sentences, sentences_words)):
            if not words:
                scores.append((0.0, idx, sentence))
                continue
            tf = _compute_tf(words)
            score = sum(tf.get(w, 0) * idf.get(w, 0) for w in words)
            position_bonus = 1.0 / (1.0 + idx * 0.1)
            scores.append((score * position_bonus, idx, sentence))
        top = sorted(scores, key=lambda x: x[0], reverse=True)[:max_sentences]
        top_sorted = sorted(top, key=lambda x: x[1])
        summary = " ".join(s[2] for s in top_sorted)
    
    if summary and summary[-1] not in ".!?":
        summary += "."

    # Basic Persona styling for fallback - Defaulting to Gen-Z "Alex" if no persona provided
    p_name = persona.get("personaName", "Alex") if persona else "Alex"
    vibes = ", ".join(persona.get("vibes", ["genz", "energetic"])).lower() if persona else "genz, energetic"
    
    if "genz" in vibes or "energetic" in vibes:
        # Just a tiny bit of flavor so it doesn't look totally robotic
        summary = f"No cap: {summary} (Insight from {p_name})"
    
    return summary


def summarize(text: str, max_sentences: int = 5, persona: dict = None, fallback_title: str = "New Insight", model_name: str = "gemini-1.5-flash") -> str:
    """
    Produce a persona-driven summary and title using Google Gemini.
    Defaults to Gen-Z "Alex" persona if none is provided.
    """
    api_key = Config.GEMINI_API_KEY
    if not api_key:
        return f"{fallback_title} | {_fallback_summarize(text, max_sentences, persona)}"

    # Restore Gen-Z Alex as the default
    p_name = persona.get("personaName", "Alex") if persona else "Alex"
    p_role = persona.get("personaRole", "Gen-Z Expert") if persona else "Gen-Z Content Expert"
    p_vibes = ", ".join(persona.get("vibes", ["gen-z", "energetic", "authentic"])) if persona else "gen-z, energetic, authentic, lit, no cap"

    # Limit text to avoid token issues and stay in free tier
    content_text = text[:10000] 
    
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    SYSTEM PROMPT:
    You are {p_name}, a {p_role}. Vibes: {p_vibes}.
    
    TASK:
    1. Summarize the text in EXACTLY 4 to 5 lines.
    2. Suggest a Meta Title (max 60 chars) and an SEO-friendly URL Slug.
    3. Provide 3-5 relevant SEO Keywords.
    4. Respond in YOUR voice with heavy use of Gen-Z slang (persona).
    
    FORMAT YOUR RESPONSE EXACTLY AS:
    [TITLE] | [SUMMARY] | [META_TITLE] | [SLUG] | [KEYWORDS]
    
    TEXT:
    {content_text}
    """
    
    # Try twice with a delay on 429
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            result = response.text.strip()
            
            # Ensure we have at least TITLE and SUMMARY
            return result
        except Exception as e:
            if "429" in str(e) and attempt == 0:
                # Extract specific wait time if provided by Google
                wait_hint = "60s"
                match = re.search(r"(\d+)s", str(e))
                if match: wait_hint = f"{match.group(1)}s"

                print(f"[Quota] [Summarizer] Quota hit for {p_name}. Needs {wait_hint} cooling off. (Retrying in 3s...)")
                time.sleep(3)
                continue
            print(f"Gemini failed for {p_name} (attempt {attempt+1}): {e}")
            break

    return f"{fallback_title} | {_fallback_summarize(text, max_sentences, persona)} | {fallback_title} | news-{int(time.time())} | news, update"
