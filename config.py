import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
env_path = ROOT_DIR / ".env"
load_dotenv(dotenv_path=env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Kolkata")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
DEFAULT_BUFFER_MINUTES = int(os.getenv("DEFAULT_BUFFER_MINUTES", "15"))
PORT = int(os.getenv("PORT", "8080"))

CREDENTIALS_FILE_PATH = ROOT_DIR / GOOGLE_CREDENTIALS_PATH
TOKEN_FILE_PATH = ROOT_DIR / GOOGLE_TOKEN_PATH

def validate_config() -> None:
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("[WARNING] TELEGRAM_BOT_TOKEN is missing or default in .env file.")