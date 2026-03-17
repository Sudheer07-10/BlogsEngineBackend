"""
scraper.py — Extracts title, description, hashtags, image, and body text from a URL.
"""

import re
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from ddgs import DDGS

# Definition of active verticals for Vertical Pulse
VERTICAL_KEYWORDS = {
    "education": ["school", "university", "learning", "edtech", "courses", "student", "teacher", "education", "degree", "curriculum"],
    "health care": ["medical", "wellness", "hospital", "doctors", "medtech", "health", "healthcare", "patient", "clinical", "surgery", "medicine", "pharmacy"],
    "ai": ["artificial intelligence", "machine learning", "llm", "automation", "robotics", "neural network", "deep learning", "generative ai", "openai", "claude", "gemini", "nvidia", "gpu"],
    "jobs": ["career", "hiring", "workforce", "recruitment", "employment", "job", "salary", "interview", "resume", "hr", "talent", "layoff"]
}

def is_content_relevant(text: str) -> bool:
    """Check if the text content matches any of the active verticals."""
    if not text:
        return False
    
    text_lower = text.lower()
    for vertical, keywords in VERTICAL_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            return True
            
    return False



HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


def _extract_hashtags_from_text(text: str) -> list[str]:
    """Pull #hashtag patterns out of any text block."""
    tags = re.findall(r"#(\w{2,})", text)
    return list(dict.fromkeys(t.lower() for t in tags))  # unique, lowercase


def _extract_keywords_as_hashtags(soup: BeautifulSoup) -> list[str]:
    """Extract meta keywords and convert to hashtag-style tags."""
    meta_kw = soup.find("meta", attrs={"name": re.compile(r"keywords", re.I)})
    if meta_kw and meta_kw.get("content"):
        raw = [kw.strip().lower().replace(" ", "") for kw in meta_kw["content"].split(",")]
        return [kw for kw in raw if kw]
    return []


def _get_meta(soup: BeautifulSoup, property_name: str) -> str | None:
    """Get content from og: or twitter: meta tags."""
    for attr in ("property", "name"):
        tag = soup.find("meta", attrs={attr: property_name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _extract_body_text(soup: BeautifulSoup) -> str:
    """Extract the main readable text from the page body."""
    # Remove script, style, nav, footer, header elements
    for unwanted in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form"]):
        unwanted.decompose()

    # Try to find main content area
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if not main:
        return ""

    paragraphs = main.find_all("p")
    text_blocks = [p.get_text(separator=" ", strip=True) for p in paragraphs if len(p.get_text(separator=" ", strip=True)) > 40]
    # Clean up double spaces that might be introduced
    text_blocks = [re.sub(r'\s+', ' ', block) for block in text_blocks]
    return "\n".join(text_blocks)


def _extract_body_images(main_soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract up to 3 relevant images from the main content."""
    images = []
    seen = set()
    
    for img in main_soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
            
        # Skip small icons/pixels if explicit dimensions are small
        w = str(img.get("width", "")).replace("px", "").strip()
        h = str(img.get("height", "")).replace("px", "").strip()
        try:
            if w and int(w) < 100: continue
            if h and int(h) < 100: continue
        except ValueError:
            pass
            
        src = urljoin(base_url, src)
        low_src = src.lower()
        if src not in seen and not low_src.endswith(".svg") and not low_src.endswith(".gif") and "avatar" not in low_src and "logo" not in low_src:
            seen.add(src)
            images.append(src)
            if len(images) == 3:
                break
                
    return images


def _extract_highlights(text: str) -> list[str]:
    """Extract interesting stats or quotes from the text."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    highlights = []
    seen = set()
    
    # Look for percentages, currency, or large words
    stat_pattern = re.compile(r'(\d+(?:\.\d+)?%|\$\d+(?:,\d{3})*(?:\.\d+)?|\b\d+\s+(?:million|billion|trillion)\b)', re.IGNORECASE)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 40 or len(sentence) > 200:
            continue
            
        if sentence in seen:
            continue
            
        if stat_pattern.search(sentence):
            highlights.append(sentence)
            seen.add(sentence)
            if len(highlights) == 3:
                break
                
    return highlights


import random
import time

def find_trending_articles(query_suffix: str = "", limit: int = 5) -> list[dict]:
    """
    Fetch trending articles specifically for the defined verticals: 
    Education, Health care, AI, and Jobs.
    """
    from duckduckgo_search import DDGS
    
    verticals = ["education", "health care", "ai", "jobs"]
    all_articles = []
    
    print(f"[Scraper] Scouting trending news for verticals: {verticals}")
    
    try:
        ddgs = DDGS()
        for vertical in verticals:
            # Create a more targeted query for each vertical
            search_query = f"{vertical} news {query_suffix}".strip()
            print(f"[Scraper] Searching news for: {search_query}")
            
            try:
                # Get top 2 results per vertical to ensure variety
                results = list(ddgs.news(search_query, max_results=3, timelimit="d"))
                
                for r in results:
                    title = r.get("title", "")
                    # Double check relevance using our existing logic
                    if is_content_relevant(title) or is_content_relevant(r.get("body", "")):
                        all_articles.append({
                            "title": title,
                            "url": r.get("url", ""),
                            "source": r.get("source", "News"),
                            "vertical": vertical.title(),
                            "snippet": r.get("body", "")
                        })
                
                # Tiny sleep to be polite to the search engine
                time.sleep(0.5)
                
            except Exception as e:
                print(f"[Scraper] Failed trending search for {vertical}: {e}")
                continue
                
        # Shuffle results so verticals are mixed, then cap at limit
        random.shuffle(all_articles)
        return all_articles[:limit]
        
    except Exception as e:
        print(f"[Scraper] Trending search global error: {e}")
        return []

def search_web_for_url(query: str, vertical: str | None = None) -> str | None:
    """Use DuckDuckGo to find a trending web article URL. Randomizes from top 5 to prevent repetition."""
    
    # 0. Prepend vertical to query if provided
    if vertical:
        query = f"{vertical} {query}".strip()
    
    # 1. Try DuckDuckGo News first (for trending, relative content)
    try:
        news_results = list(DDGS().news(query, max_results=5))
        if news_results and len(news_results) > 0:
            return random.choice(news_results).get("url")
    except Exception as exc:
        print(f"DuckDuckGo news search failed for '{query}': {exc}")

    # 2. Try DuckDuckGo Standard Text Search (general web)
    try:
        results = list(DDGS().text(query, max_results=5))
        if results and len(results) > 0:
            return random.choice(results).get("href")
    except Exception as exc:
        print(f"DuckDuckGo search failed for '{query}': {exc}")
    
    # 3. Fallback to standard Wikipedia OpenSearch API
    try:
        search_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={requests.utils.quote(query)}&limit=1&format=json"
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"Wikipedia fallback search failed for '{query}': {exc}")

    return None


def find_related_articles(query_or_url: str, limit: int = 5, vertical: str | None = None) -> list[dict]:
    """Find related articles from diverse publishers to present as options."""
    print(f"[Scraper] Finding related coverage for: {query_or_url} (Vertical: {vertical})")
    
    search_term = query_or_url
    if vertical and not (query_or_url.startswith("http://") or query_or_url.startswith("https://")):
        search_term = f"{vertical} {query_or_url}".strip()
    original_option = None
    
    if query_or_url.startswith("http://") or query_or_url.startswith("https://"):
        try:
            print("[Scraper] Query is a URL. Fetching original title...")
            metadata = scrape_url(query_or_url)
            search_term = metadata.get("title", "")
            original_option = {
                "title": metadata.get("title", "Original Link"),
                "url": query_or_url,
                "source": metadata.get("domain", "Original Source")
            }
        except Exception as e:
            print(f"[Scraper] Failed to fetch original URL title: {str(e)}")
            pass # Fall back to searching the raw URL string

    try:
        from duckduckgo_search import DDGS
        results = DDGS().news(keywords=search_term, max_results=20, timelimit="w")
        
        options = []
        # Normalizing source names to catch 'www.nextgov.com' vs 'NEXTGOV'
        def normalize_source(s):
            return re.sub(r'^(www\.)?|\.com$|\.org$|\.net$', '', s.lower()).strip()

        seen_titles = set()
        seen_urls = set()
        seen_sources = set()

        # If original_option is relevant, add it first
        if original_option and is_content_relevant(original_option["title"]):
            options.append(original_option)
            seen_titles.add(original_option["title"].lower().strip())
            seen_urls.add(original_option["url"].lower().split('?')[0])
            seen_sources.add(normalize_source(original_option["source"]))
        
        if results:
            for r in results:
                if len(options) >= limit:
                    break
                
                title = r.get("title", "No Title").strip()
                # Secondary filtering: Check if title contains vertical keywords
                if not is_content_relevant(title):
                    continue

                norm_title = title.lower()
                url = r.get("url", "").split('?')[0].lower()
                source = r.get("source", "Unknown")
                norm_source = normalize_source(source)
                
                if norm_title not in seen_titles and url not in seen_urls and norm_source not in seen_sources:
                    options.append({
                        "title": title,
                        "url": r.get("url", ""),
                        "source": source,
                        "snippet": r.get("body", "") # Store the search snippet as fallback
                    })
                    seen_titles.add(norm_title)
                    seen_urls.add(url)
                    seen_sources.add(norm_source)
                    
        return options
    except Exception as e:
        print(f"[Scraper] News Search failed: {str(e)}")
        return [original_option] if original_option else []


def scrape_url(url: str) -> dict:
    """
    Scrape a URL and return structured data.
    
    Returns:
        {
            "url": str,
            "domain": str,
            "title": str,
            "description": str,
            "body_text": str,
            "hashtags": list[str],
            "image_url": str | None,
        }
    """
    try:
        # Do not use custom headers; let curl_cffi impersonate Chrome perfectly
        resp = requests.get(url, timeout=30, allow_redirects=True, impersonate="chrome")
        # Explicitly check for 403s before it raises RequestException
        if resp.status_code in [403, 401, 429]:
            raise ValueError(f"HTTP Error {resp.status_code}")
        resp.raise_for_status()
        html_content = resp.text
    except Exception as exc:
        print(f"Direct scrape blocked or failed for {url}. Attempting DDG fallback: {exc}")
        # Search DuckDuckGo strictly for the URL to extract a snippet
        domain = urlparse(url).netloc
        try:
            results = list(DDGS().text(url, max_results=2))
            if results and len(results) > 0:
                res = results[0]
                # Return a synthesized result using the DDG snippet body
                return {
                    "url": url,
                    "domain": domain,
                    "title": res.get("title", domain),
                    "description": res.get("body", "No description available."),
                    "body_text": res.get("body", "No description available."),
                    "hashtags": ["#News", "#Info", "#Article"],
                    "image_url": None,
                    "content_images": [],
                    "callout_stats": [],
                }
            else:
                raise ValueError("Both direct scrape and DDG fallback failed.")
        except Exception as fallback_exc:
            print(f"DDG Fallback also failed: {fallback_exc}. Using ultra fallback.")
            # Ultra fallback: just use the URL segment as title so it never crashes
            title_fallback = url.rstrip('/').split('/')[-1].replace('-', ' ').title() or domain
            return {
                "url": url,
                "domain": domain,
                "title": title_fallback,
                "description": "Content could not be automatically extracted due to strict anti-bot protections.",
                "body_text": "Content could not be automatically extracted due to strict anti-bot protections.",
                "hashtags": ["#Article", "#Info"],
                "image_url": None,
                "content_images": [],
                "callout_stats": [],
            }

    soup = BeautifulSoup(html_content, "lxml")

    # --- Title ---
    title = (
        _get_meta(soup, "og:title")
        or _get_meta(soup, "twitter:title")
        or (soup.title.string.strip() if soup.title and soup.title.string else "")
        or "Untitled"
    )

    # --- Description ---
    description = (
        _get_meta(soup, "og:description")
        or _get_meta(soup, "twitter:description")
        or _get_meta(soup, "description")
        or ""
    )

    # --- Image ---
    image_url = (
        _get_meta(soup, "og:image")
        or _get_meta(soup, "twitter:image")
    )

    # --- Body text ---
    body_text = _extract_body_text(soup)

    # --- Highlights & Content Images ---
    # Because _extract_body_text decomposes unwanted elements, soup is now stripped of garbage
    main_content = soup.find("article") or soup.find("main") or soup.find("body") or soup
    content_images = _extract_body_images(main_content, url)
    callout_stats = _extract_highlights(body_text)

    # --- Hashtags ---
    hashtags: list[str] = []
    hashtags.extend(_extract_keywords_as_hashtags(soup))
    hashtags.extend(_extract_hashtags_from_text(body_text))
    hashtags.extend(_extract_hashtags_from_text(description))

    # Deduplicate
    seen = set()
    unique_hashtags = []
    for h in hashtags:
        if h not in seen:
            seen.add(h)
            unique_hashtags.append(h)

    # If no hashtags found, generate from title words
    if not unique_hashtags:
        title_words = re.findall(r"\b[a-zA-Z]{4,}\b", title.lower())
        unique_hashtags = list(dict.fromkeys(title_words))[:5]

    domain = urlparse(url).netloc

    return {
        "url": url,
        "domain": domain,
        "title": title,
        "description": description,
        "body_text": body_text,
        "hashtags": unique_hashtags[:10],  # cap at 10
        "image_url": image_url,
        "content_images": content_images,
        "callout_stats": callout_stats,
    }
