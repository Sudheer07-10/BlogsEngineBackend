"""
store.py — Supabase-based persistence for content cards.
"""

from datetime import datetime, timezone
import logging
from supabase import create_client, Client
from config import Config

# supabase client instance (initialized lazily)
_supabase_client = None

def _get_supabase() -> Client:
    """Lazy initializer for Supabase client."""
    global _supabase_client
    if _supabase_client is None:
        if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _supabase_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _supabase_client

def get_all_links(table_name: str) -> list[dict]:
    """Return all stored content cards from the specified Supabase table, newest first."""
    try:
        response = _get_supabase().table(table_name)\
            .select("*")\
            .order("created_at", desc=True)\
            .execute()
        return response.data
    except Exception as e:
        logging.error(f"Error fetching links from Supabase table {table_name}: {e}")
        return []

def get_link(table_name: str, link_id: str) -> dict | None:
    """Return a single content card by its ID from the specified Supabase table, or None if not found."""
    try:
        response = _get_supabase().table(table_name)\
            .select("*")\
            .eq("id", link_id)\
            .execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        logging.error(f"Error fetching link {link_id} from Supabase table {table_name}: {e}")
    return None

def save_link(table_name: str, card: dict) -> dict:
    """
    Save a new content card to the specified Supabase table.

    Args:
        table_name: The target table name in Supabase.
        card: dict with keys like title, summary, hashtags, url, etc.

    Returns:
        The saved card with id and created_at fields added by Supabase.
    """
    try:
        # Prepare data for Supabase
        # Note: id and created_at are handled by Supabase defaults
        data = {
            "url": card.get("url"),
            "domain": card.get("domain"),
            "title": card.get("title"),
            "description": card.get("description"),
            "summary": card.get("summary"),
            "hashtags": card.get("hashtags", []),
            "image_url": card.get("image_url"),
            "content_images": card.get("content_images", []),
            "callout_stats": card.get("callout_stats", [])
        }
        
        response = _get_supabase().table(table_name)\
            .insert(data)\
            .execute()
            
        if response.data:
            return response.data[0]
        raise Exception("No data returned from insert")
    except Exception as e:
        logging.error(f"Error saving link to Supabase table {table_name}: {e}")
        # Fallback: re-raise or handle as needed
        raise e

def delete_link(table_name: str, link_id: str) -> bool:
    """Delete a content card by ID from the specified Supabase table. Returns True if successful."""
    try:
        response = _get_supabase().table(table_name)\
            .delete()\
            .eq("id", link_id)\
            .execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error deleting link {link_id} from Supabase table {table_name}: {e}")
        return False

# --- Pending Selections ---

def get_all_pending_selections() -> list[dict]:
    """Return all stored pending selections from Supabase, newest first."""
    try:
        response = _get_supabase().table("pending_selections")\
            .select("*")\
            .order("created_at", desc=True)\
            .execute()
        return response.data
    except Exception as e:
        logging.error(f"Error fetching pending selections from Supabase: {e}")
        return []

def get_pending_selection(selection_id: str) -> dict | None:
    """Return a single pending selection context by its ID from Supabase."""
    try:
        response = _get_supabase().table("pending_selections")\
            .select("*")\
            .eq("id", selection_id)\
            .execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        logging.error(f"Error fetching pending selection {selection_id} from Supabase: {e}")
    return None

def save_pending_selection(selection: dict) -> dict:
    """Save a new pending selection context to Supabase."""
    try:
        # We store the raw dictionary in a JSONB column named 'data'
        data = {"data": selection}
        response = _get_supabase().table("pending_selections")\
            .insert(data)\
            .execute()
        if response.data:
            return response.data[0]
        raise Exception("No data returned from insert")
    except Exception as e:
        logging.error(f"Error saving pending selection to Supabase: {e}")
        raise e

def delete_pending_selection(selection_id: str) -> bool:
    """Delete a pending selection context by ID from Supabase."""
    try:
        response = _get_supabase().table("pending_selections")\
            .delete()\
            .eq("id", selection_id)\
            .execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error deleting pending selection {selection_id} from Supabase: {e}")
        return False


