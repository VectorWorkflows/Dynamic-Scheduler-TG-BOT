import os
import threading
import uvicorn
from fastapi import FastAPI
import config
from src.bot import start_bot

app = FastAPI(
    title="Vector Workflows - Dynamic Scheduler",
    description="Threaded FastAPI Engine + Telegram Bot Daemon"
)

@app.get("/")
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Vector Workflows | Dynamic Scheduler",
        "bot_running": True
    }

def launch_bot_thread():
    try:
        start_bot()
    except Exception as e:
        print(f"[CRITICAL] Bot thread crashed: {e}")

if __name__ == "__main__":
    config.validate_config()

    # Launch Telegram Bot in background daemon thread
    bot_thread = threading.Thread(target=launch_bot_thread, daemon=True)
    bot_thread.start()
    print("✅ Background Bot thread launched successfully.")

    # Launch FastAPI Web Server
    port = int(os.getenv("PORT", config.PORT))
    print(f"🌐 FastAPI Web Server listening on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)