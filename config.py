import os
import logging
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class Config:
    """Centralized configuration for Vertical Pulse."""
    
    # API Configurations
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
    
    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    # Application Flow
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    BACKEND_PORT = int(os.getenv("BACKEND_PORT", 8000))
    
    # Security
    # In production, this should be a comma-separated list of origins
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

    @classmethod
    def validate(cls):
        """Ensure critical environment variables are present."""
        missing = []
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
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
