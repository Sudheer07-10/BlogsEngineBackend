import sys
import os

# Add parent directory to path
sys.path.append(os.getcwd())

from scraper import find_related_articles

query = "AI news"
print(f"Testing find_related_articles with query: {query}")
results = find_related_articles(query, limit=5, vertical="AI")
print(f"Results found: {len(results)}")
for r in results:
    print(f"- {r['title']} ({r['source']})")
