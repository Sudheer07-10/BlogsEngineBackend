from scraper import find_related_articles

query = "Education"
print(f"Testing discovery for: {query}")
options = find_related_articles(query, limit=5, vertical="education")
print(f"Found {len(options)} options.")
for i, opt in enumerate(options):
    print(f"{i+1}. {opt['title']} ({opt['source']})")
