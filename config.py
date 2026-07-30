import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
env_path = ROOT_DIR / ".env"
load_dotenv(dotenv_path=env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Kolkata")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
PORT = int(os.getenv("PORT", "8080"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080")
MONGO_URI = os.getenv("MONGO_URI", "")

CREDENTIALS_FILE_PATH = ROOT_DIR / GOOGLE_CREDENTIALS_PATH