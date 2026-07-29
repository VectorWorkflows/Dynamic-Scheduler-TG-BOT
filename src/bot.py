import time
import requests
import config
from src.calendar_service import generate_circadian_schedule

def send_telegram_message(chat_id: int, text: str) -> None:
    """Sends a Markdown-formatted message back to Telegram."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")


def handle_message(message: dict) -> None:
    """Processes incoming command messages from Telegram."""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    print(f"[LOG] Received command: '{text}' from Chat ID: {chat_id}")

    if text.startswith("/awake"):
        parts = text.split()
        if len(parts) < 2:
            send_telegram_message(chat_id, "⚠️ **Usage:** `/awake HH:MM` (e.g. `/awake 07:30`)")
            return

        time_str = parts[1]
        try:
            send_telegram_message(chat_id, f"🔄 Calculating circadian blocks for `{time_str}` and updating Google Calendar...")
            events = generate_circadian_schedule(time_str)

            response_lines = [f"✅ **Circadian Day Scheduled for {time_str}!**\n"]
            for ev in events:
                response_lines.append(f"• **{ev['title']}**: {ev['start']} - {ev['end']}")

            send_telegram_message(chat_id, "\n".join(response_lines))

        except ValueError:
            send_telegram_message(chat_id, "❌ **Error:** Time format must be `HH:MM` (24-hour clock, e.g. `07:30` or `08:15`).")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ **Error generating schedule:** `{str(e)}`")

    elif text.startswith("/start") or text.startswith("/help"):
        send_telegram_message(
            chat_id,
            "👋 **Welcome to Vector Workflows | Dynamic Scheduler!** (@vector_86k_bot)\n\n"
            "Send `/awake HH:MM` (e.g. `/awake 07:30`) when you wake up, and I will automatically populate your Google Calendar with buffered deep-work blocks."
        )


def start_bot() -> None:
    """Long-polling loop for Telegram updates."""
    config.validate_config()
    print("🚀 Vector Workflows Telegram Bot started. Listening for updates...")
    offset = None
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"

    while True:
        try:
            params = {"timeout": 30, "offset": offset}
            response = requests.get(url, params=params, timeout=35)
            if response.status_code == 200:
                data = response.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_message(update["message"])
            else:
                print(f"[WARNING] Non-200 status code from Telegram API: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"[CONNECTION ERROR] Telegram poll failed: {e}. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"[UNEXPECTED ERROR] {e}")
            time.sleep(2)