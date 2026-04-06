import os
import logging
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Config:
    """Centralized configuration for Vertical Pulse."""
    
    # API Configurations
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    # X (Twitter) API Keys
    X_API_KEY = os.getenv("X_API_KEY")
    X_API_SECRET = os.getenv("X_API_SECRET")
    X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
    X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET")
    
    # LinkedIn API Keys
    LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
    LINKEDIN_PERSON_ID = os.getenv("LINKEDIN_PERSON_ID")
    
    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    # Application Flow
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:9010")
    BACKEND_PORT = int(os.getenv("BACKEND_PORT", 9020))
    
    # Security
    # In production, this should be a comma-separated list of origins
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    BASE_URL = os.getenv("BASE_URL") # Required for Webhooks (e.g. https://api.yourdomain.com)

    @property
    def TELEGRAM_WEBHOOK_URL(self):
        if not self.BASE_URL:
            return None
        return f"{self.BASE_URL.rstrip('/')}/api/telegram/webhook"

    @classmethod
    def validate(cls):
        """Ensure critical environment variables are present."""
        missing = []
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY:
            missing.append("SUPABASE_KEY")
            
        if missing:
            logging.warning(f"Missing critical environment variables: {', '.join(missing)}")
            logging.warning("System may run in limited/fallback mode.")
        else:
            logging.info("Configuration loaded and validated successfully.")

# Initialize and validate on import
Config.validate()
