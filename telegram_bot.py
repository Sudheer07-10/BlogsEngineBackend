import os
import re
import asyncio
import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# We import the core functions directly from the backend to process URLs locally
from scraper import scrape_url, search_web_for_url, find_related_articles
from summarizer import summarize
from store import save_link, get_link, save_pending_selection, get_pending_selection, delete_pending_selection
from urllib.parse import quote_plus
from config import Config

# Get the API tokens from environment variables
TELEGRAM_BOT_TOKEN = Config.TELEGRAM_BOT_TOKEN
# Telegram API rejects "localhost" as an invalid URL for inline keyboards. Use 127.0.0.1 instead.
FRONTEND_URL = Config.FRONTEND_URL

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_message = (
        f"Hi {user.first_name}! 👋\n\n"
        "I am the Vertical Pulse Bot.\n"
        "1. Drop a URL/Topic to directly scrape it.\n"
        "2. Send /trending to discover top articles across the web."
    )
    await update.message.reply_text(welcome_message)

async def fetch_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch top trending articles across specific verticals and display them."""
    from scraper import find_trending_articles
    
    await update.message.reply_text("🔎 Scouting for the freshest news in Education, Health, AI, and Jobs...")
    
    # Run in thread so we don't block
    loop = asyncio.get_running_loop()
    
    # Now calls the updated scraper which handles verticals internally
    articles = await loop.run_in_executor(None, find_trending_articles, "", 8) 
    
    if not articles:
        await update.message.reply_text("⚠️ No fresh trending articles found in your verticals right now.")
        return
        
    reply = "🔥 <b>Top Trending in Your Verticals:</b>\n\n"
    
    for idx, art in enumerate(articles, 1):
        vertical_label = art.get("vertical", "General")
        title = html.escape(art.get("title", "No Title"))
        source = html.escape(art.get("source", "Source"))
        url = art.get("url", "#")
        
        reply += f"{idx}. <b>[{vertical_label}]</b> {title}\n"
        reply += f"<i>via {source}</i> — <a href='{url}'>Read Article</a>\n\n"
    
    reply += "✨ <i>Send me any of these URLs (or a topic) to generate a summary!</i>"
    
    await update.message.reply_text(reply, parse_mode="HTML", disable_web_page_preview=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages. Search, pre-summarize 5 options, and ask the user to pick one."""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Check for greetings
    greetings = ["hi", "hello", "hey", "sup", "yo", "morning", "afternoon", "evening"]
    if text.lower() in greetings:
        welcome_back = (
            f"Hello! 👋 I'm ready to help you discover new articles.\n\n"
            "What topics would you like to discover today? "
            "(e.g., 'Latest in AI', 'Healthcare tech', 'Education trends', or 'Jobs in data science')\n\n"
            "Or just paste a link to summarize it directly!"
        )
        await update.message.reply_text(welcome_back)
        return
    
    processing_msg = await update.message.reply_text("⏳ Searching the web and summarizing 5 related articles... (This may take a moment)")
    
    try:
        loop = asyncio.get_running_loop()
        
        # 1. Find 5 diverse articles
        def get_options():
            return find_related_articles(text, limit=5)
            
        options = await loop.run_in_executor(None, get_options)
        
        if not options:
            await processing_msg.edit_text("❌ No relevant coverage found in your selected verticals (Education, Health care, AI, Jobs).")
            return

        # 2. Pre-summarize every option
        def pre_summarize_options(opts):
            summarized_opts = []
            for idx, opt in enumerate(opts):
                try:
                    # Run a faster, shallower scrape just to get the body text for summarization
                    # We will reuse this data if the user selects it
                    scraped_data = scrape_url(opt['url'])
                    body = scraped_data.get("body_text", "")
                    if len(body) < 150:
                        # Fallback to scraper description or DDG snippet
                        body = scraped_data.get("description", "") or opt.get("snippet", "")
                    
                    if len(body) < 50:
                        body = f"{opt['title']}. {opt.get('snippet', '')}"

                    summary_text = summarize(body, max_sentences=3)
                    # If AI fails, use snippet
                    if not summary_text or len(summary_text.strip()) < 10:
                        summary_text = opt.get("snippet") or scraped_data.get("description") or opt['title']
                        
                    # Bundle the full scraped data and the summary so we don't have to scrape it again later
                    opt['summary'] = summary_text
                    opt['full_data'] = scraped_data
                    summarized_opts.append(opt)
                except Exception as e:
                    print(f"Failed to pre-summarize option {idx}: {e}")
                    opt['summary'] = "Failed to generate summary."
                    opt['full_data'] = None
                    summarized_opts.append(opt)
            return summarized_opts

        summarized_options = await loop.run_in_executor(None, pre_summarize_options, options)

        # 3. Save to pending state
        request_data = {
            "submitter_chat_id": chat_id,
            "query": text,
            "options": summarized_options
        }
        
        def save_state():
            return save_pending_selection(request_data)
            
        saved_state = await loop.run_in_executor(None, save_state)
        selection_id = saved_state['id']

        # 4. Build the massive menu message
        message_pieces = [f"🔍 <b>Found {len(summarized_options)} Options for:</b> <i>{html.escape(text[:50])}</i>\n"]
        keyboard = []

        for i, opt in enumerate(summarized_options):
            idx = i + 1
            title = html.escape(opt['title'])
            domain = html.escape(opt['source'])
            summary = html.escape(opt['summary'])
            url = opt['url']
            
            message_pieces.append(f"<b>{idx}. {title}</b> ({domain})\n<i>{summary}</i>\n<a href='{url}'>Read Source</a>\n")
            
            # The callback data now tells the bot WHICH option index was clicked
            keyboard.append([InlineKeyboardButton(f"✅ Process Option #{idx}", callback_data=f"select_option|{selection_id}|{i}")])

        keyboard.append([InlineKeyboardButton("❌ Reject All (Cancel)", callback_data=f"reject_selection|{selection_id}")])

        final_msg_text = "\n".join(message_pieces) + "\n👇 <b>Choose one to publish to the Hub:</b>"
        
        await processing_msg.edit_text(final_msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML", disable_web_page_preview=True)
        
    except Exception as e:
        await processing_msg.edit_text(f"❌ Failed to process: {str(e)}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from the inline keyboard."""
    query = update.callback_query
    await query.answer() # Acknowledge the click
    
    data = query.data
    
    if data.startswith("select_option|"):
        _, selection_id, option_index = data.split("|")
        option_index = int(option_index)
        chat_id = update.effective_chat.id
        
        # 1. Retrieve the pending selection
        loop = asyncio.get_running_loop()
        def get_state():
            return get_pending_selection(selection_id)
            
        pending_state = await loop.run_in_executor(None, get_state)
        
        if not pending_state:
            await query.edit_message_text("❌ This selection menu has expired or was already processed.")
            return

        # Security check: Ensure only the original submitter can click it
        if pending_state.get('submitter_chat_id') != chat_id:
            await query.answer("❌ Only the person who requested this can select an option.", show_alert=True)
            return

        selected_opt = pending_state['options'][option_index]
        await query.edit_message_text(f"⏳ <i>Publishing Option {option_index + 1}: {html.escape(selected_opt['title'])}...</i>", parse_mode="HTML")

        try:
            # 2. Build the final Hub Card from the pre-scraped data
            def build_and_save():
                scraped = selected_opt.get('full_data')
                if not scraped:
                    raise ValueError("Missing scraped data for this option. Try again.")
                
                # Assemble the card data identically to `process_link_sync`
                card_data = {
                    "url": scraped["url"],
                    "domain": scraped["domain"],
                    "title": scraped["title"],
                    "description": scraped.get("description", ""),
                    "summary": selected_opt["summary"], # Use the pre-generated summary!
                    "hashtags": scraped.get("hashtags", []),
                    "image_url": scraped.get("image_url"),
                    "content_images": scraped.get("content_images", []),
                    "callout_stats": scraped.get("callout_stats", []),
                }
                save_link(card_data)
                # Cleanup
                delete_pending_selection(selection_id)
                return card_data
                
            saved_card = await loop.run_in_executor(None, build_and_save)
            
            # 3. Send final success message
            reply = format_card_reply(saved_card)
            if saved_card.get('image_url'):
                try:
                    await context.bot.send_photo(chat_id=chat_id, photo=saved_card['image_url'])
                except: pass
            
            keyboard = [[InlineKeyboardButton("🌐 View & Share Options", callback_data=f"share_menu|{saved_card['id']}")]]
            await query.edit_message_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            
        except Exception as e:
             await query.edit_message_text(f"❌ Failed to publish article: {str(e)}")

    elif data.startswith("reject_selection|"):
        _, selection_id = data.split("|", 1)
        chat_id = update.effective_chat.id
        
        loop = asyncio.get_running_loop()
        def get_state():
            return get_pending_selection(selection_id)
            
        pending_state = await loop.run_in_executor(None, get_state)
        
        if pending_state and pending_state.get('submitter_chat_id') != chat_id:
             await query.answer("❌ Only the person who requested this can cancel it.", show_alert=True)
             return
             
        def cleanup():
            delete_pending_selection(selection_id)
        await loop.run_in_executor(None, cleanup)
        
        await query.edit_message_text("❌ <i>Request cancelled. No articles were published.</i>", parse_mode="HTML")

    elif data.startswith("share_menu|"):
        card_id = data.split("|", 1)[1]
        card = get_link(card_id)
        if not card:
            await query.answer("Article not found in database!", show_alert=True)
            return
            
        share_url = f"{FRONTEND_URL}/card/{card_id}"
        twitter_url = f"https://twitter.com/intent/tweet?url={quote_plus(share_url)}&text={quote_plus(card.get('title', ''))}"
        linkedin_url = f"https://www.linkedin.com/sharing/share-offsite/?url={quote_plus(share_url)}"
        
        keyboard = [
            [InlineKeyboardButton("🌐 Open in Hub", url=share_url)],
            [
                InlineKeyboardButton("🐦 Twitter", url=twitter_url),
                InlineKeyboardButton("💼 LinkedIn", url=linkedin_url),
                InlineKeyboardButton("📸 Instagram", callback_data="ig_share")
            ],
            [InlineKeyboardButton("🔙 Back to Main Card", callback_data=f"back_menu|{card_id}")]
        ]
        
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "ig_share":
        await query.answer("Instagram doesn't support direct link sharing! Copy the Hub link instead.", show_alert=True)
        
    elif data.startswith("back_menu|"):
        card_id = data.split("|", 1)[1]
        keyboard = [[InlineKeyboardButton("🌐 View & Share Options", callback_data=f"share_menu|{card_id}")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# --- formatting helper ---

def format_card_reply(card: dict) -> str:
    """Format the card data into the Telegram message matching the UI reference using robust HTML."""
    title = html.escape(card.get('title', 'Unknown Title'))
    summary = html.escape(card.get('summary', 'No summary available.'))
    url = card.get('url', '')
    hashtags_list = card.get('hashtags', [])
    hashtags_str = " ".join([f"#{html.escape(tag)}" for tag in hashtags_list]) if hashtags_list else "#Tech"
    
    # Generate SEO items based on content
    meta_title = html.escape(card.get('title', 'Unknown Title')[:60])
    # Keep alphanumeric and spaces, lowercase, replace spaces with hyphens
    url_slug = html.escape(re.sub(r'[^a-z0-9]+', '-', card.get('title', 'Unknown Title').lower()).strip('-'))
    
    # Take first sentence of summary for Meta Description
    meta_desc_match = re.split(r'(?<=[.!?])\s+', card.get('summary', 'No summary available.'))
    meta_desc = html.escape(meta_desc_match[0][:150] if meta_desc_match else card.get('summary', 'No summary available.')[:150])
    
    # Top keywords
    keywords_str = html.escape(", ".join(hashtags_list[:6]) if hashtags_list else "Tech, News")
    
    # Compile the final string
    return (
        f"<b>Title</b>\n"
        f"{title} 🚀\n\n"
        f"<b>Summary</b>\n"
        f"{summary}\n\n"
        f"<b>Source Link</b>\n"
        f"🔗 {url}\n\n"
        f"<b>Hashtags</b>\n"
        f"{hashtags_str}\n\n"
        f"🔍 <b>SEO Optimization</b>\n\n"
        f"<i>Meta Title</i>\n{meta_title}\n\n"
        f"<i>URL Slug</i>\n{url_slug}\n\n"
        f"<i>Meta Description</i>\n{meta_desc}\n\n"
        f"<i>Keywords (comma separated)</i>\n{keywords_str}"
    )

def process_link_sync(text: str) -> dict:
    """Synchronous wrapper for the scraping and summarizing logic from main.py"""
    url_str = text
    
    # 1. Topic or URL?
    if not url_str.startswith("http://") and not url_str.startswith("https://"):
        found_url = search_web_for_url(url_str)
        if not found_url:
            raise ValueError(f"Could not find a trending web article for topic: '{url_str}'")
        url_str = found_url

    # 2. Scrape
    scraped = scrape_url(url_str)
    
    # 3. Summarize
    body = scraped.get("body_text", "")
    if len(body) < 100:
        body = scraped.get("description", "")
        
    summary_text = summarize(body, max_sentences=3)
    if not summary_text:
        summary_text = scraped.get("description")
    
    # Strictly enforce a fallback string so HTML doesn't render an empty block
    if not summary_text or not summary_text.strip():
        summary_text = "No summary available. The article could not be automatically summarized due to content restrictions."
        
    # 4. Build card data
    return {
        "url": scraped["url"],
        "domain": scraped["domain"],
        "title": scraped["title"],
        "description": scraped.get("description", ""),
        "summary": summary_text,
        "hashtags": scraped.get("hashtags", []),
        "image_url": scraped.get("image_url"),
        "content_images": scraped.get("content_images", []),
        "callout_stats": scraped.get("callout_stats", []),
    }

def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable not set.")
        print("Please set it before running the bot.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("trending", fetch_trending))

    # on button clicks
    application.add_handler(CallbackQueryHandler(button_callback))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Telegram Bot is running! Waiting for messages...")
    
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
