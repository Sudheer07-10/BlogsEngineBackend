"""
main.py — FastAPI backend for the Traffic Content System.

Endpoints:
    POST /api/links  — submit a URL, get back a summarized content card
    GET  /api/links  — list all published content cards
    DELETE /api/links/{id} — delete a specific card
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import scrape_url, search_web_for_url
from summarizer import summarize
from store import save_link, get_all_links, get_link, delete_link

from config import Config

app = FastAPI(
    title="Vertical Pulse",
    description="Paste a link → get a summarized content card with hashtags",
    version="1.0.1",
)

# Hardened CORS: Use allowed origins from config
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ───────────────────────────────────────────

class LinkSubmission(BaseModel):
    url: str
    vertical: str | None = None
    platform: str = "cp" # Enum: cp, sakhi, jobs


class DiscoveryRequest(BaseModel):
    query: str
    vertical: str | None = None
    platform: str = "cp"


class DiscoveryOption(BaseModel):
    title: str
    url: str
    source: str
    summary: str
    full_data: dict | None = None


class DiscoveryResponse(BaseModel):
    query: str
    options: list[DiscoveryOption]


# --- Multi-Table Mapping Helpers ---
PLATFORM_TABLE_MAP = {
    "cp": "cp_blogs",
    "sakhi": "sakhi_blogs",
    "jobs": "jobs_blogs"
}

def get_target_table(platform: str) -> str:
    """Map platform identifier to Supabase table name."""
    return PLATFORM_TABLE_MAP.get(platform, "cp_blogs")


class ContentCard(BaseModel):
    id: str
    url: str
    domain: str
    title: str
    description: str
    summary: str
    hashtags: list[str]
    image_url: str | None = None
    content_images: list[str] = []
    callout_stats: list[str] = []
    created_at: str                 


# ── Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/discover", response_model=DiscoveryResponse)
async def discover_articles(payload: DiscoveryRequest):
    """
    Search for 5 related articles and pre-summarize them.
    (Matches the logic used in the Telegram bot)
    """
    query = payload.query.strip()
    from scraper import find_related_articles
    
    # 1. Find options
    options = find_related_articles(query, limit=5, vertical=payload.vertical)
    
    if not options:
        raise HTTPException(
            status_code=404, 
            detail="No relevant coverage found in your selected verticals (Education, Health care, AI, Jobs)."
        )

    # 2. Summarize each option
    summarized_options = []
    for opt in options:
        try:
            scraped = scrape_url(opt['url'])
            body = scraped.get("body_text", "")
            if len(body) < 150: # Increased threshold for better AI input
                # Fallback 1: Scraper's meta description
                # Fallback 2: The snippet from the news search results (discovery time)
                body = scraped.get("description", "") or opt.get("snippet", "")
            
            # If body is still very short, use title + snippet as context
            if len(body) < 50:
                body = f"{opt['title']}. {opt.get('snippet', '')}"

            sum_text = summarize(body, max_sentences=3)
            # Ensure we ALWAYS have at least something to show
            if not sum_text or len(sum_text.strip()) < 10:
                sum_text = opt.get("snippet") or scraped.get("description") or opt['title']
            
            summarized_options.append(DiscoveryOption(
                title=opt['title'],
                url=opt['url'],
                source=opt['source'],
                summary=sum_text,
                full_data=scraped
            ))
        except Exception as e:
            print(f"Failed to summarize web discovery option: {e}")
            summarized_options.append(DiscoveryOption(
                title=opt['title'],
                url=opt['url'],
                source=opt['source'],
                summary="Failed to generate summary.",
                full_data=None
            ))

    return DiscoveryResponse(query=query, options=summarized_options)


@app.post("/api/publish", response_model=ContentCard)
async def publish_discovered_article(option: DiscoveryOption, platform: str = "cp"):
    """
    Save a pre-summarized article directly to the Hub.
    """
    if not option.full_data:
        raise HTTPException(status_code=400, detail="Missing full data for publishing.")
        
    scraped = option.full_data
    table_name = get_target_table(platform)
    print(f"DEBUG: Publishing to platform='{platform}', table='{table_name}'")
    
    card_data = {
        "url": scraped["url"],
        "domain": scraped["domain"],
        "title": scraped["title"],
        "description": scraped.get("description", ""),
        "summary": option.summary,
        "hashtags": scraped.get("hashtags", []),
        "image_url": scraped.get("image_url"),
        "content_images": scraped.get("content_images", []),
        "callout_stats": scraped.get("callout_stats", []),
    }
    
    saved = save_link(table_name, card_data)
    return saved


@app.post("/api/links", response_model=ContentCard)
async def submit_link(payload: LinkSubmission):
    """
    Accept a URL, scrape it, summarize it, and store the content card.
    """
    url_str = payload.url.strip()

    try:
        if not url_str.startswith("http://") and not url_str.startswith("https://"):
            # It's a topic search query
            from scraper import search_web_for_url
            found_url = search_web_for_url(url_str, vertical=payload.vertical)
            if not found_url:
                raise ValueError(f"Could not find a trending web article for topic: '{url_str}'")
            url_str = found_url

        scraped = scrape_url(url_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {exc}")

    # Summarize the body text (fall back to description if body is too short)
    body = scraped.get("body_text", "")
    if len(body) < 100:
        body = scraped.get("description", "")
    
    summary = summarize(body, max_sentences=3)
    
    # If summarizer produced nothing, use description directly
    if not summary:
        summary = scraped.get("description", "No summary available.")
    
    # Build the card
    card_data = {
        "url": scraped["url"],
        "domain": scraped["domain"],
        "title": scraped["title"],
        "description": scraped.get("description", ""),
        "summary": summary,
        "hashtags": scraped.get("hashtags", []),
        "image_url": scraped.get("image_url"),
        "content_images": scraped.get("content_images", []),
        "callout_stats": scraped.get("callout_stats", []),
    }

    table_name = get_target_table(payload.platform)
    print(f"DEBUG: Submitting link to platform='{payload.platform}', table='{table_name}'")
    saved = save_link(table_name, card_data)
    return saved


@app.get("/api/links", response_model=list[ContentCard])
async def list_links(platform: str = "cp"):
    """Return all published content cards for a platform, newest first."""
    table_name = get_target_table(platform)
    return get_all_links(table_name)


@app.get("/api/links/{link_id}", response_model=ContentCard)
async def get_single_link(link_id: str, platform: str | None = None):
    """
    Return a single content card by ID.
    Always searches the specified platform first, then falls back to others.
    """
    if platform:
        table_name = get_target_table(platform)
        card = get_link(table_name, link_id)
        if card:
            return card
            
    # Fallback: Search all tables if not found
    for p_id, t_name in PLATFORM_TABLE_MAP.items():
        card = get_link(t_name, link_id)
        if card:
            return card
            
    raise HTTPException(status_code=404, detail="Link not found")


@app.delete("/api/links/{link_id}")
async def remove_link(link_id: str, platform: str = "cp"):
    """Delete a content card by its ID."""
    table_name = get_target_table(platform)
    deleted = delete_link(table_name, link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"status": "deleted", "id": link_id}


@app.get("/")
async def root():
    return {"message": "Traffic Content System API is running ✨"}
