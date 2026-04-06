import logging
import json
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from scraper import scrape_url, find_related_articles
from summarizer import summarize
from store import save_link
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gen-Z Persona for the bot (On-Demand)
GENZ_PERSONA = {
    "personaName": "Z-Bot",
    "personaRole": "Gen-Z Trend Analyst",
    "vibes": ["gen-z", "slang", "no cap", "lit", "fr", "aesthetic", "vibrant", "authentic"]
}

class TelegramHandler:
    def __init__(self, token: str):
        self.token = token
        # We initialize the application but we won't call run_polling()
        # Instead, we'll use it to process updates from the webhook
        self.application = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Register command and message handlers."""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show platform selection buttons."""
        keyboard = [
            [InlineKeyboardButton("🕉 Janmasethu", callback_data="platform_sakhi")],
            [InlineKeyboardButton("📚 Course Platform", callback_data="platform_cp")],
            [InlineKeyboardButton("💼 Jobs", callback_data="platform_jobs")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_text = (
            "👋 *Welcome to the Traffic Content Bot!*\n\n"
            "Please select the platform you want to publish to:"
        )
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming text: handle edits first, then search/links."""
        # 1. Check if we are in an EDIT state
        edit_state = context.user_data.get('edit_state')
        if edit_state:
            await self._handle_edit_input(update, context, edit_state)
            return

        # 2. Check for platform selection
        platform = context.user_data.get('platform')
        if not platform:
            await self.start_command(update, context)
            return

        text = update.message.text.strip()
        
        if text.startswith("http://") or text.startswith("https://"):
            await self._process_link(update, text, context)
        else:
            await self._process_search(update, text, context)

    async def _handle_edit_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
        """Update the content field based on user input."""
        new_value = update.message.text.strip()
        
        if 'last_content' not in context.user_data:
            await update.message.reply_text("⚠️ *No content to edit*. Send a link first.")
            context.user_data['edit_state'] = None
            return

        if field == "TITLE":
            context.user_data['last_content']['title'] = new_value
        elif field == "SUMMARY":
            context.user_data['last_content']['summary'] = new_value
        elif field == "HASHTAGS":
            # Ensure hashtags start with # and are correctly formatted
            tags = [t if t.startswith("#") else f"#{t}" for t in new_value.replace(",", " ").split()]
            context.user_data['last_content']['hashtags'] = tags

        # Clear state and show updated preview
        context.user_data['edit_state'] = None
        await update.message.reply_text(f"✅ *{field} Updated!*", parse_mode="Markdown")
        await self._send_preview(update, context)

    async def _process_link(self, update: Update, url: str, context: ContextTypes.DEFAULT_TYPE):
        """Scrape URL and show the data 'as it is' from the source."""
        status_msg = await update.message.reply_text("🔍 *Scraping source content...*", parse_mode="Markdown")
        
        try:
            scraped = scrape_url(url)
            
            # Prioritize raw data "as it is" to ensure no blank summaries
            title = scraped.get("title", "Untitled Article")
            
            # Summary Fallback Chain: description -> first chunk of body -> placeholder
            summary = scraped.get("description", "").strip()
            if not summary or len(summary) < 10:
                summary = scraped.get("body_text", "")[:400].strip() + "..."
            if not summary or len(summary) < 20:
                summary = "No description available on-page. Pulling raw content highlights."

            hashtags = scraped.get("hashtags", [])

            # Store temporary data in user_data
            context.user_data['last_content'] = {
                "url": url,
                "domain": scraped.get("domain"),
                "title": title,
                "summary": summary,
                "hashtags": hashtags,
                "image_url": scraped.get("image_url"),
                "content_images": scraped.get("content_images", []),
                "description": scraped.get("description", ""),
                "body_text": scraped.get("body_text", ""), # Keep for on-demand summarizing
                "meta_title": title,
                "slug": f"bot-{url.split('/')[-1][:20]}",
                "keywords": "news, telegram"
            }

            await status_msg.delete()
            await self._send_preview(update, context)

        except Exception as e:
            logger.error(f"Link scraping error: {e}")
            await status_msg.edit_text(f"❌ *Scraping Error*: {str(e)}\n\n_Make sure the link is a direct blog post._", parse_mode="Markdown")

    async def _send_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays content preview exactly like the requested screenshot."""
        content = context.user_data.get('last_content')
        if not content: return

        platform = context.user_data.get('platform', 'cp')
        platform_name = "Janmasethu" if platform == "sakhi" else ("Course Platform" if platform == "cp" else "Jobs")

        # Formatting to match the screenshot exactly (escaping sensitive Markdown)
        title = content['title'].replace("*", "\\*").replace("_", "\\_").replace("[", "\\[")
        source = content['domain'].replace("*", "\\*").replace("_", "\\_")
        summary = content['summary'].replace("*", "\\*").replace("_", "\\_").replace("[", "\\[")
        hashtags = [h.replace("*", "\\*").replace("_", "\\_") for h in content['hashtags']]

        preview_text = (
            f"*Title*: {title}\n"
            f"*Source*: {source}\n\n"
            f"*GenZ Summary*:\n{summary}\n\n"
            f"*Hashtags*: {' '.join(hashtags)}\n\n"
            f"Ready to publish this to your website and social platforms?"
        )

        keyboard = [
            [InlineKeyboardButton("🚀 Proceed to Publish", callback_data="publish_now")],
            [InlineKeyboardButton("🔄 Pick Another", callback_data="pick_another")],
            [
                InlineKeyboardButton("✏️ Title", callback_data="edit_title"),
                InlineKeyboardButton("📝 Summary", callback_data="edit_summary"),
                InlineKeyboardButton("🏷️ Tags", callback_data="edit_hashtags")
            ]
        ]
        # Only add the AI button if we haven't summarized yet or it's requested
        if "GenZ Summary" not in content['summary'] and "no cap" not in content['summary'].lower():
             keyboard.insert(1, [InlineKeyboardButton("✨ Slangify with Gen-Z AI", callback_data="gen_z_sum")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send as new message
        if update.callback_query:
            await update.callback_query.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(preview_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _process_search(self, update: Update, query: str, context: ContextTypes.DEFAULT_TYPE):
        """Search for related articles and offer a numbered list of options."""
        status_msg = await update.message.reply_text(f"🔎 *Searching for*: {query}...", parse_mode="Markdown")
        
        try:
            articles = find_related_articles(query, limit=5)
            if not articles:
                await status_msg.edit_text("😕 *No articles found*. Try another keyword.")
                return

            await status_msg.delete()
            
            # Reset search results
            context.user_data['search_results'] = {}
            
            msg_lines = [f"✅ *Found {len(articles)} related articles for '{query}':*\n"]
            keyboard_row = []
            
            for i, art in enumerate(articles, 1):
                ref_id = f"art_{i}_{int(time.time())}"
                context.user_data['search_results'][ref_id] = art['url']
                
                # Escape markdown special characters in Title and Source
                # especially '_' and '*' which are common in tech titles/URLs
                title = art['title'].replace("*", "\\*").replace("_", "\\_").replace("[", "\\[")
                source = art.get('source', 'Web').replace("*", "\\*").replace("_", "\\_")
                url = art['url'] # URLs are tricky, let's keep them raw but Markdown parser might still choke
                
                # Format each entry like the screenshot
                msg_lines.append(
                    f"{i}. *{title}*\n"
                    f"📰 _{source}_\n"
                    f"🔗 {url}\n"
                )
                
                # Create a selection button
                keyboard_row.append(InlineKeyboardButton(str(i), callback_data=f"sum_{ref_id}"))

            msg_lines.append("Select a number to preview and publish:")
            
            # Chunk buttons into rows of 5 if needed
            keyboard = [keyboard_row[i:i + 5] for i in range(0, len(keyboard_row), 5)]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            full_msg = "\n".join(msg_lines)
            await update.message.reply_text(full_msg, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            try:
                await status_msg.edit_text(f"❌ *Search Error*: {str(e)[:100]}", parse_mode="Markdown")
            except:
                await update.message.reply_text(f"❌ *Search Error*: {str(e)[:100]}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button interactions."""
        query = update.callback_query
        await query.answer()
        data = query.data

        if data.startswith("platform_"):
            platform = data.replace("platform_", "")
            context.user_data['platform'] = platform
            p_name = "Janmasethu" if platform == "sakhi" else ("Course Platform" if platform == "cp" else "Jobs")
            await query.edit_message_text(f"🚀 *Selected: {p_name}*\n\nSend a **URL** or **Topic** to fetch content.", parse_mode="Markdown")

        elif data == "publish_now":
            content = context.user_data.get('last_content')
            platform = context.user_data.get('platform', 'cp')
            if not content:
                await query.edit_message_text("❌ Session expired. Please send the link again."); return

            try:
                table = "sakhi_blogs" if platform == "sakhi" else ("cp_blogs" if platform == "cp" else "jobs_blogs")
                save_link(table, content)
                p_name = "Janmasethu" if platform == "sakhi" else ("Course Platform" if platform == "cp" else "Jobs")
                await query.edit_message_text(f"✅ *Published to {p_name}!*", parse_mode="Markdown")
                context.user_data['last_content'] = None
            except Exception as e:
                await query.edit_message_text(f"❌ *Failed*: {str(e)}")

        elif data == "gen_z_sum":
            content = context.user_data.get('last_content')
            if not content: return
            
            m = await query.message.reply_text("✨ *Gen-Z Bot is cooking...*", parse_mode="Markdown")
            try:
                # Use body text for better summarizing
                text_to_sum = content.get('body_text') or content.get('summary')
                result = summarize(text_to_sum, max_sentences=3, persona=GENZ_PERSONA)
                parts = [p.strip() for p in result.split("|")]
                
                content['title'] = parts[0] if len(parts) > 0 else content['title']
                content['summary'] = parts[1] if len(parts) > 1 else result
                
                await m.delete()
                await self._send_preview(update, context)
            except Exception as e:
                await m.edit_text(f"⚠️ *Summarization busy*: {str(e)}\n_You can still edit manually._")

        elif data == "edit_title":
            context.user_data['edit_state'] = "TITLE"
            await query.message.reply_text("✏️ *Send the new Title:*", parse_mode="Markdown")
        elif data == "edit_summary":
            context.user_data['edit_state'] = "SUMMARY"
            await query.message.reply_text("📝 *Send the new Summary:*", parse_mode="Markdown")
        elif data == "edit_hashtags":
            context.user_data['edit_state'] = "HASHTAGS"
            await query.message.reply_text("🏷️ *Send new Hashtags (space separated):*", parse_mode="Markdown")

        elif data == "pick_another":
            # Simple restart for now
            await self.start_command(update, context)

        elif data.startswith("sum_"):
            ref_id = data.replace("sum_", "")
            url = context.user_data.get('search_results', {}).get(ref_id)
            if url:
                # When selecting from search results, let's auto-summarize with Gen-Z style
                # but handle fallback gracefully
                m = await query.message.reply_text("✨ *Fetching & Slangifying...*", parse_mode="Markdown")
                try:
                    scraped = scrape_url(url)
                    body = scraped.get("body_text") or scraped.get("description") or ""
                    
                    # Call summarizer with Gen-Z persona immediately as requested in screenshot
                    result = summarize(body, max_sentences=3, persona=GENZ_PERSONA)
                    parts = [p.strip() for p in result.split("|")]
                    
                    context.user_data['last_content'] = {
                        "url": url,
                        "domain": scraped.get("domain"),
                        "title": parts[0] if len(parts) > 0 else scraped.get("title", "Untitled"),
                        "summary": parts[1] if len(parts) > 1 else result,
                        "hashtags": scraped.get("hashtags", []),
                        "image_url": scraped.get("image_url"),
                        "content_images": scraped.get("content_images", []),
                        "description": scraped.get("description", ""),
                        "body_text": scraped.get("body_text", ""),
                        "meta_title": scraped.get("title"),
                        "slug": f"bot-{int(time.time())}",
                        "keywords": "news"
                    }
                    
                    await m.delete()
                    await self._send_preview(update, context)
                except Exception as e:
                    logger.error(f"Selection error: {e}")
                    await m.edit_text(f"⚠️ *Error fetching content*: {str(e)}")

    async def process_update(self, data: dict):
        update = Update.de_json(data, self.application.bot)
        await self.application.initialize()
        await self.application.process_update(update)
        await self.application.shutdown()

    async def initialize_application(self):
        await self.application.initialize()
        await self.application.start()

    async def register_webhook(self, url: str):
        if not self.token or not url: return False
        try:
            success = await self.application.bot.set_webhook(url=url)
            return success
        except Exception as e:
            logger.error(f"Webhook Error: {e}"); return False

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token: print("❌ Token missing")
    else:
        print("🤖 Bot Live (Polling Mode)...")
        handler = TelegramHandler(token)
        handler.application.run_polling()
