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
import asyncio
from datetime import datetime, timezone
import logging

from scraper import scrape_url, search_web_for_url
from summarizer import summarize
from store import save_link, get_all_links, get_link, delete_link, get_stats_counts

from config import Config
from telegram_handler import TelegramHandler

app = FastAPI(
    title="Vertical Pulse",
    description="Paste a link → get a summarized content card with hashtags",
    version="1.0.2",
)

# Initialize Telegram Handler
tg_bot = TelegramHandler(Config.TELEGRAM_BOT_TOKEN)

class SignupRequest(BaseModel):
    email: str
    password: str
    platform: str # e.g. cp_blogs, sakhi_blogs, jobs_blogs

class LoginRequest(BaseModel):
    email: str
    password: str

# Hardened CORS: Use allowed origins from config
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auto-Posting Background Worker ---

async def autopost_worker():
    """Background task to automatically publish ripe scheduled posts."""
    print("🤖 [Auto-Post Worker] Active and waiting for scheduled posts...")
    from store import get_ripe_scheduled_posts, save_link, delete_scheduled_post
    
    while True:
        try:
            ripe_posts = get_ripe_scheduled_posts()
            
            for post in ripe_posts:
                print(f"🤖 [Auto-Post] Publishing '{post.get('title')}' for platform {post.get('platform')}...")
                
                # Reconstruct card data for publishing
                from urllib.parse import urlparse
                full_data = post.get("full_data") or {}
                source_url = post.get("source_url") or ""
                
                domain = full_data.get("domain")
                if not domain and source_url:
                    domain = urlparse(source_url).netloc
                if not domain:
                    domain = "unknown"
                    
                # Robust Image fallback for Auto-Post
                image_url = post.get("image_url")
                c_images = post.get("content_images", [])
                
                if not image_url and full_data: 
                    image_url = full_data.get("image_url")
                if not c_images and full_data:
                    c_images = full_data.get("content_images", [])

                card_data = {
                    "url": post.get("source_url"),
                    "domain": domain,
                    "title": post.get("title"),
                    "description": post.get("meta_description") or "",
                    "summary": post.get("summary"),
                    "hashtags": post.get("hashtags", []),
                    "image_url": image_url,
                    "content_images": c_images,
                    "callout_stats": post.get("full_data", {}).get("callout_stats", []) if post.get("full_data") else [],
                    "meta_title": post.get("meta_title"),
                    "slug": post.get("slug"),
                    "keywords": post.get("keywords")
                }
                
                table_name = get_target_table(post.get("platform", "cp"))
                
                # Save to live table
                save_link(table_name, card_data)
                
                # Delete from schedule
                delete_scheduled_post(str(post.get("id")))
                
                print(f"🤖 [Auto-Post] Successfully published and removed from queue: {post.get('id')}")
        except Exception as e:
            print(f"❌ [Auto-Post Worker] Error during check: {e}")
            
        # Check every 60 seconds
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(autopost_worker())
    
    # Register Telegram Webhook
    webhook_url = Config().TELEGRAM_WEBHOOK_URL
    if webhook_url:
        await tg_bot.register_webhook(webhook_url)
    else:
        print("⚠️ [Telegram] BASE_URL not set. Webhook registration skipped.")


# ── Request / Response Models ───────────────────────────────────────────

class LinkSubmission(BaseModel):
    url: str
    vertical: str | None = None
    platform: str = "cp" # Enum: cp, sakhi, jobs
    persona: dict | None = None

class DiscoveryRequest(BaseModel):
    query: str
    vertical: str | None = None
    platform: str = "cp"
    persona: dict | None = None


class DiscoveryOption(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    full_data: dict | None = None
    summary: str | None = None
    # Support for user-edited SEO fields during publish
    seo: dict | None = None
    hashtags: list[str] = []

class UserConfigRequest(BaseModel):
    user_id: str
    email: str
    platform: str
    config: dict

class DiscoveryResponse(BaseModel):
    query: str
    options: list[DiscoveryOption]


class SummarizeRequest(BaseModel):
    text: str
    persona: dict | None = None


class ScheduleSubmission(BaseModel):
    platform: str
    title: str | None = None
    summary: str | None = None
    meta_title: str | None = None
    slug: str | None = None
    meta_description: str | None = None
    keywords: str | None = None
    hashtags: list[str] | None = None
    source_url: str | None = None
    full_data: dict | None = None
    scheduled_for: str | None = None  # ISO 8601 string
    status: str = "DRAFTING"

class ScheduleUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    scheduled_for: str | None = None
    status: str | None = None
    hashtags: list[str] | None = None


# --- Multi-Table Mapping Helpers ---
PLATFORM_TABLE_MAP = {
    "cp": "cp_blogs",
    "sakhi": "sakhi_blogs",
    "jobs": "jobs_blogs"
}

PLATFORM_VERTICAL_MAP = {
    "cp": "ai",
    "sakhi": "health care",
    "jobs": "jobs"
}

def get_target_table(platform: str) -> str:
    """Map platform identifier to Supabase table name."""
    return PLATFORM_TABLE_MAP.get(platform, "cp_blogs")

def get_default_vertical(platform: str) -> str:
    """Return a smart default vertical based on platform."""
    return PLATFORM_VERTICAL_MAP.get(platform, "ai")


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
    Search for 5 related articles and provide a quick persona-based summary.
    """
    query = payload.query.strip()
    platform = payload.platform or "cp"
    vertical = payload.vertical or get_default_vertical(platform)
    
    from scraper import find_related_articles
    options = find_related_articles(query, limit=5, vertical=vertical)
    
    if not options:
        return DiscoveryResponse(query=query, options=[])

    summarized_options = []
    for opt in options:
        try:
            # Use the search snippet for a QUICK initial persona summary
            # This avoids scraping 5 full websites and saves massively on token quota
            snippet = opt.get("snippet") or opt.get("body") or opt['title']
            
            # Generate a quick persona-driven summary from the snippet
            # Pass original title as fallback if persona summarizer fails
            result = summarize(
                f"Snippet: {snippet}", 
                max_sentences=2, 
                persona=payload.persona, 
                fallback_title=opt['title']
            )
            
            if "|" in result:
                parts = [p.strip() for p in result.split("|")]
                persona_title = parts[0] if len(parts) > 0 else opt['title']
                persona_summary = parts[1] if len(parts) > 1 else (result if "|" not in result else "Analysis complete.")
            else:
                persona_title, persona_summary = opt['title'], result

            summarized_options.append(DiscoveryOption(
                title=persona_title,
                url=opt['url'],
                source=opt['source'],
                summary=persona_summary,
                full_data=None # Will be populated on selection
            ))
        except Exception as e:
            logging.error(f"Error in discovery summary: {e}")
            summarized_options.append(DiscoveryOption(
                title=opt['title'],
                url=opt['url'],
                source=opt['source'],
                summary=opt.get("snippet") or "Article discovered. Click to summarize.",
                full_data=None
            ))

    return DiscoveryResponse(query=query, options=summarized_options)


@app.post("/api/summarize-persona")
async def summarize_persona(payload: SummarizeRequest):
    """
    Take any text and return a persona-driven summary with SEO metadata.
    """
    if not payload.text:
        raise HTTPException(status_code=400, detail="Text is required for summarization.")
    
    # Generate persona-driven summary
    result = summarize(payload.text, max_sentences=3, persona=payload.persona)
    
    parts = [p.strip() for p in result.split("|")]
    
    # Default fallbacks
    data = {
        "title": parts[0] if len(parts) > 0 else "New Update",
        "summary": parts[1] if len(parts) > 1 else result,
        "meta_title": parts[2] if len(parts) > 2 else (parts[0] if len(parts) > 0 else "New Update"),
        "slug": parts[3] if len(parts) > 3 else f"update-{int(time.time())}",
        "keywords": parts[4] if len(parts) > 4 else "news, update"
    }
    
    return data


@app.post("/api/publish", response_model=ContentCard)
async def publish_discovered_article(option: DiscoveryOption, platform: str = "cp"):
    """
    Save a pre-summarized article directly to the Hub. 
    Implements Just-In-Time (JIT) scraping if metadata is missing.
    """
    from scraper import scrape_url
    from urllib.parse import urlparse

    # 1. JIT Metadata Retrieval
    scraped = option.full_data
    if not scraped:
        print(f"🔍 [JIT Scrape] Fetching missing metadata for discovery candidate: {option.url}")
        try:
            scraped = scrape_url(option.url)
        except Exception as e:
            print(f"⚠️ [JIT Scrape] Scraper blocked or failed ({e}). Using minimal fallback.")
            scraped = {
                "url": option.url,
                "domain": urlparse(option.url).netloc or platform,
                "title": option.title,
                "hashtags": [],
                "image_url": None,
                "content_images": [],
                "description": ""
            }
        
    table_name = get_target_table(platform)
    print(f"DEBUG: JIT Publish to platform='{platform}', table='{table_name}'")
    
    # 2. Merge user-edits with source metadata
    # Map frontend 'seo' keys to backend database field names
    seo = option.seo or {}
    
    card_data = {
        "url": scraped.get("url") or option.url,
        "domain": scraped.get("domain") or urlparse(option.url).netloc,
        "title": option.title or scraped.get("title") or "Untitled",
        "description": scraped.get("description", "") or option.snippet or "",
        "summary": option.summary, # User rewritten content
        "hashtags": option.hashtags if option.hashtags else scraped.get("hashtags", []),
        "image_url": scraped.get("image_url"),
        "content_images": scraped.get("content_images", []),
        "callout_stats": scraped.get("callout_stats", []),
        # Persist SEO metadata
        "meta_title": seo.get("metaTitle"),
        "slug": seo.get("slug"),
        "keywords": seo.get("keywords")
    }
    
    # 3. Save to live Blog Hub
    saved = save_link(table_name, card_data)
    if not saved:
        raise HTTPException(status_code=500, detail="Database persistence failed for published candidate.")
    return saved


@app.post("/api/links", response_model=ContentCard)
async def submit_link(payload: LinkSubmission):
    """
    Accept a URL, scrape it, persona-summarize it, and store the content card.
    """
    url_str = payload.url.strip()

    try:
        if not url_str.startswith("http://") and not url_str.startswith("https://"):
            from scraper import search_web_for_url
            vertical = payload.vertical or get_default_vertical(payload.platform)
            found_url = search_web_for_url(url_str, vertical=vertical)
            if not found_url:
                raise ValueError(f"Could not find a trending web article for topic: '{url_str}'")
            url_str = found_url

        scraped = scrape_url(url_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {exc}")

    body = scraped.get("body_text", "")
    if len(body) < 100:
        body = scraped.get("description", "")
    
    # 1. Usepersona summarizer (generates title | summary | meta_title | slug | keywords)
    result = summarize(body, max_sentences=3, persona=payload.persona)
    
    # 2. Parse result
    parts = [p.strip() for p in result.split("|")]
    gen_title = parts[0] if len(parts) > 0 else scraped["title"]
    gen_summary = parts[1] if len(parts) > 1 else result
    gen_meta_title = parts[2] if len(parts) > 2 else gen_title
    gen_slug = parts[3] if len(parts) > 3 else f"news-{int(time.time())}"
    gen_keywords = parts[4] if len(parts) > 4 else "news, update"

    card_data = {
        "url": scraped["url"],
        "domain": scraped["domain"],
        "title": gen_title,
        "description": scraped.get("description", ""),
        "summary": gen_summary,
        "hashtags": scraped.get("hashtags", []),
        "image_url": scraped.get("image_url"),
        "content_images": scraped.get("content_images", []),
        "callout_stats": scraped.get("callout_stats", []),
        "meta_title": gen_meta_title,
        "slug": gen_slug,
        "keywords": gen_keywords
    }

    table_name = get_target_table(payload.platform)
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


@app.post("/api/links/{link_id}/track")
async def track_interaction_endpoint(link_id: str, field: str, platform: str = "cp"):
    """Increment views or clicks for a specific post."""
    from store import track_interaction
    table_name = get_target_table(platform)
    success = track_interaction(table_name, link_id, field)
    if not success:
        raise HTTPException(status_code=404, detail="Link not found or invalid field.")
    return {"status": "success", "field": field, "id": link_id}

@app.get("/jobs/feed")
async def get_jobs_feed(skip: int = 0, limit: int = 20):
    """Placeholder for jobs feed to resolve 404 errors."""
    return {"jobs": [], "total": 0}


@app.get("/users/me")
async def get_current_user():
    """Placeholder for current user to resolve 404 errors."""
    return {"id": "guest", "username": "guest", "role": "viewer"}


# --- ROUTES MOVE TO TOP ---
@app.post("/api/signup")
async def signup(req: SignupRequest):
    """Register a new user config."""
    import uuid
    from store import save_user_config
    # Generate a proper UUID to avoid PostgreSQL 22P02 (invalid UUID representation) errors
    user_id = str(uuid.uuid4())
    print(f"DEBUG: Initializing new user {user_id} for {req.email}")
    success = save_user_config(user_id, req.email, req.platform, {"vibes": [], "role": "editor"})
    
    if not success:
        print(f"ERROR: Failed to initialize database record for {req.email}")
        raise HTTPException(status_code=500, detail="Database initialization failed. Please check Supabase connectivity.")
        
    return {"status": "success", "user": {"id": user_id, "email": req.email, "platform": req.platform}}

@app.post("/api/login")
async def login(req: LoginRequest):
    """Simple login (placeholder since password logic was removed)."""
    from store import get_user_config
    # For now, we assume simple ID-based or email-based 'login' without password verification
    # since the backend store refactor removed the password_hash logic.
    return {
        "status": "success",
        "user": {
            "id": "21ea4e73-f065-4089-aa48-bc0cbbae61bd", # Default test id from logs
            "email": req.email,
            "role": "editor",
            "platform": "cp",
            "config": {}
        }
    }

@app.get("/api/user/config")
async def get_config_endpoint(user_id: str):
    """Fetch the persona configuration for a specific user ID."""
    from store import get_user_config
    config_record = get_user_config(user_id)
    if config_record is None:
        raise HTTPException(status_code=404, detail="User config not found.")
    return config_record.get("config", {})

@app.post("/api/user/config")
async def save_config_endpoint(req: UserConfigRequest):
    """Save/Update the persona configuration for a specific user ID."""
    from store import save_user_config
    print(f"DEBUG: Received config update for {req.user_id} ({req.email})")
    try:
        success = save_user_config(req.user_id, req.email, req.platform, req.config)
        if not success:
            raise HTTPException(status_code=500, detail="Database upsert failed (check store logs)")
        return {"status": "success", "config": req.config}
    except Exception as e:
        print(f"ERROR: save_config_endpoint failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_dashboard_stats(platform: str = None):
    """
    Return exact counts for the dashboard. 
    If a platform is provided, it only returns stats for that specific database table.
    """
    from store import get_stats_counts
    
    # Isolation: Use only the user's platform if provided, otherwise default to all
    tables = [get_target_table(platform)] if platform else ["cp_blogs", "sakhi_blogs", "jobs_blogs"]
    stats = get_stats_counts(platform_tables=tables)
    
    return [
        {"label": "Published Posts", "value": str(stats["total_published"]), "icon": "📝", "change": "real-time"},
        {"label": "Average Engagement", "value": f"{stats['avg_engagement']}%", "icon": "🔥", "change": "tracked"},
        {"label": "Pipeline Queue", "value": str(stats["pipeline_queue"]), "icon": "⚡", "change": "pending"},
        {"label": "Total Reach", "value": f"{stats['total_reach'] // 1000}K" if stats['total_reach'] >= 1000 else str(stats['total_reach']), "icon": "☁️", "change": "views"}
    ]

@app.get("/api/activity")
async def get_recent_activity(platform: str = "cp"):
    """
    Return the 5 most recent activities by combining published posts and scheduled posts.
    """
    from store import get_all_links, get_scheduled_posts
    try:
        table_name = get_target_table(platform)
        published = get_all_links(table_name)
        scheduled = get_scheduled_posts(platform)
        
        activities = []
        
        for p in published:
            activities.append({
                "id": str(p.get("id")),
                "title": p.get("title", "Untitled"),
                "url": p.get("url"), # Added for source link
                "type": "Published",
                "time": p.get("created_at"),
                "created_at_dt": p.get("created_at"),
                "views": p.get("views") or 0,
                "clicks": p.get("clicks") or 0,
                "summary": p.get("summary") or "",
                "image_url": p.get("image_url"),
                "content_images": p.get("content_images") or [],
                "hashtags": p.get("hashtags") or []
            })
            
        for s in scheduled:
            activities.append({
                "id": str(s.get("id")),
                "title": s.get("title", "Untitled"),
                "url": s.get("source_url"), # Added for source link
                "type": "Scheduled",
                "time": s.get("scheduled_for"),
                "created_at_dt": s.get("scheduled_for"),
                "summary": s.get("summary") or "Coming soon...",
                "hashtags": s.get("hashtags") or []
            })
            
        activities.sort(key=lambda x: str(x.get("created_at_dt") or ""), reverse=True)
        return activities[:5]
    except Exception as exc:
        return [{"title": f"ERR: {str(exc)}", "type": "Error", "time": None, "created_at_dt": ""}]

@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "version": "1.0.2"}

# --- Schedule Endpoints ---

@app.get("/api/schedule")
async def get_schedule(platform: str = "cp"):
    """Get all scheduled posts for a platform."""
    from store import get_scheduled_posts
    return get_scheduled_posts(platform)

@app.post("/api/schedule")
async def create_schedule(payload: ScheduleSubmission):
    """Save a scheduled post."""
    from store import save_scheduled_post
    post_data = payload.dict(exclude_unset=True)
    if "hashtags" in post_data and not post_data["hashtags"]:
        post_data["hashtags"] = []
    saved = save_scheduled_post(post_data)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save scheduled post")
    return saved

@app.put("/api/schedule/{post_id}")
async def update_schedule(post_id: str, payload: ScheduleUpdateRequest):
    """Update a scheduled post."""
    from store import update_scheduled_post
    updates = payload.dict(exclude_unset=True)
    updated = update_scheduled_post(post_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Scheduled post not found or failed to update")
    return updated

@app.delete("/api/schedule/{post_id}")
async def remove_schedule(post_id: str):
    """Delete a scheduled post."""
    from store import delete_scheduled_post
    deleted = delete_scheduled_post(post_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    return {"status": "deleted", "id": post_id}

@app.post("/api/schedule/{post_id}/publish")
async def publish_schedule_now(post_id: str):
    """Immediately publish a scheduled post regardless of its scheduled time."""
    from store import get_scheduled_post_by_id, save_link, delete_scheduled_post
    post = get_scheduled_post_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
        
    try:
        card_data = {
            "url": post.get("source_url") or "",
            "domain": post.get("full_data", {}).get("domain") if post.get("full_data") else "",
            "title": post.get("title") or "Untitled",
            "description": post.get("meta_description") or "",
            "summary": post.get("summary") or "",
            "hashtags": post.get("hashtags", []),
            "image_url": post.get("full_data", {}).get("image_url") if post.get("full_data") else None,
            "content_images": post.get("full_data", {}).get("content_images", []) if post.get("full_data") else [],
            "callout_stats": post.get("full_data", {}).get("callout_stats", []) if post.get("full_data") else [],
            "meta_title": post.get("meta_title"),
            "slug": post.get("slug"),
            "keywords": post.get("keywords")
        }
        
        table_name = get_target_table(post.get("platform", "cp"))
        save_link(table_name, card_data)
        delete_scheduled_post(post_id)
        return {"status": "success", "id": post_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/trigger-autopost")
async def manual_trigger_autopost():
    """Manually trigger the auto-posting cycle for testing and verification."""
    from store import get_ripe_scheduled_posts, save_link, delete_scheduled_post
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        ripe_posts = get_ripe_scheduled_posts()
        processed = []
        errors = []
        
        for post in ripe_posts:
            try:
                card_data = {
                    "url": post.get("source_url") or "",
                    "domain": post.get("full_data", {}).get("domain") if post.get("full_data") else "",
                    "title": post.get("title") or "Untitled",
                    "description": post.get("meta_description") or "",
                    "summary": post.get("summary") or "",
                    "hashtags": post.get("hashtags", []),
                    "image_url": post.get("full_data", {}).get("image_url") if post.get("full_data") else None,
                    "content_images": post.get("full_data", {}).get("content_images", []) if post.get("full_data") else [],
                    "callout_stats": post.get("full_data", {}).get("callout_stats", []) if post.get("full_data") else [],
                }
                
                table_name = get_target_table(post.get("platform", "cp"))
                save_link(table_name, card_data)
                delete_scheduled_post(str(post.get("id")))
                processed.append(post.get("id"))
            except Exception as e:
                errors.append({"id": post.get("id"), "error": str(e)})
                
        return {"status": "success", "processed_ids": processed, "errors": errors, "time": now_iso, "found": len(ripe_posts)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/analytics")
async def get_real_analytics(platform: str = "cp"):
    """
    Generate real-time analytics and AI-driven learning signals.
    """
    from store import get_detailed_analytics
    from summarizer import summarize
    try:
        table_name = get_target_table(platform)
        data = get_detailed_analytics(table_name)
        
        # AI Insight: Generate a learning signal based on recent posts
        recent_context = "\n".join([f"- {p['title']} (Views: {p['views']}, Clicks: {p['clicks']})" for p in data['recent_posts']])
        
        prompt = f"""
        Analyze these recent blog posts for a {platform} blog engine:
        {recent_context}
        
        Generate a one-sentence "Learning Signal" for the persona. 
        Focus on what's working (e.g. content types, tones).
        Format: [INSIGHT]
        """
        
        ai_signal = summarize(prompt)
        data["learning_signal"] = ai_signal.replace("[", "").replace("]", "").strip()
        
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/analytics/apply-suggestion")
async def apply_ai_suggestion(user_id: str, suggestion: str):
    """
    Update the user's persona vibes based on the AI learning signal.
    """
    from store import update_user_persona
    try:
        # Simple logic: If suggestion mentions 'slang', add a 'slang' vibe
        # In a real app, we might use NLP or structured output from the AI
        updates = {}
        if "slang" in suggestion.lower():
            updates["vibes"] = ["gen-z", "slang", "authentic"]
        elif "educational" in suggestion.lower():
            updates["vibes"] = ["smart", "helpful", "curated"]
            
        if updates:
            update_user_persona(user_id, updates)
            
        return {"status": "success", "applied": updates}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/track/site")
async def register_site_visit(platform: str, url: str):
    """Register a site-wide visit from the universal tracker."""
    from store import track_site_visit
    success = track_site_visit(platform, url)
    return {"status": "tracked" if success else "failed"}

@app.post("/api/telegram/webhook")
async def telegram_webhook(update: dict):
    """Handle incoming Telegram updates."""
    try:
        await tg_bot.process_update(update)
    except Exception as e:
        logging.error(f"Telegram Webhook Error: {e}")
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Traffic Content System API is running ✨", "version": app.version}
