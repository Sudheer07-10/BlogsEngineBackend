from duckduckgo_search import DDGS

try:
    with DDGS() as ddgs:
        results = list(ddgs.text("AI news", max_results=5))
        print(f"Found {len(results)} results")
        for r in results:
            print(f"- {r['title']}")
except Exception as e:
    print(f"Error: {e}")
