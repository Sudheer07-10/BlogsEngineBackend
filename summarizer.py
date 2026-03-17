"""
summarizer.py — Extractive text summarizer using TF-IDF scoring.
No external APIs or keys required.
"""

import math
import re
from collections import Counter


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


import os
from google import genai
from google.genai import types

def _fallback_summarize(text: str, max_sentences: int = 3) -> str:
    """Old TF-IDF fallback if Gemini fails or api key is missing."""
    if not text or not text.strip():
        return ""

    sentences = _split_sentences(text)
    
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    sentences_words = [_tokenize(s) for s in sentences]
    idf = _compute_idf(sentences_words)

    scores: list[tuple[float, int, str]] = []
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
    
    return summary

from config import Config

def summarize(text: str, max_sentences: int = 3) -> str:
    """
    Produce a GenZ style summary using Google Gemini 2.5 Flash.
    Falls back to mathematical TF-IDF if API key is missing.
    """
    api_key = Config.GEMINI_API_KEY
    if not api_key:
        return _fallback_summarize(text, max_sentences)

    try:
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are an expert at GenZ internet culture and slang. 
        Your job is to summarize the following article in EXACTLY 2 to 3 sentences.
        Use heavy but natural-sounding GenZ slang (e.g., "no cap", "main character energy", "dropped the tea", "mid", "W", "L", "rent free", "delulu", "NPC").
        Make it sound incredibly engaging, hyped, and relatable to a very young audience so they click to read more.
        Do NOT use emojis, just the text.
        CRITICAL: DO NOT start your summary with "Okay, so". 
        You MAY start with phrases like "Basically", "Listen up", or "Alright", or start immediately with the core hook.
        
        ARTICLE:
        {text[:15000]} # Cap at 15k chars for safety
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API GenZ Summarizer failed: {e}. Falling back to TF-IDF.")
        return _fallback_summarize(text, max_sentences)
