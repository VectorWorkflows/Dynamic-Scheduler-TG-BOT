from pymongo import MongoClient
import config

client = MongoClient(config.MONGO_URI)
db = client['vector_workflows']
users_collection = db['google_tokens']

def save_user_token(chat_id: str, token_dict: dict):
    users_collection.update_one(
        {"chat_id": str(chat_id)},
        {"$set": {"token": token_dict}},
        upsert=True
    )

def get_user_token(chat_id: str) -> dict:
    user = users_collection.find_one({"chat_id": str(chat_id)})
    return user.get("token") if user else None

def delete_user_token(chat_id: str):
    users_collection.update_one({"chat_id": str(chat_id)}, {"$unset": {"token": ""}})

def get_user_profile(chat_id: str) -> dict:
    """Fetches user profile or generates default settings."""
    user = users_collection.find_one({"chat_id": str(chat_id)})
    profile = user.get("profile", {}) if user else {}
    
    if not profile:
        profile = {
            "is_initialized": False,
            "mode_24h": False,
            "wake_window": {"earliest": "04:00", "latest": "12:00"},
            "slot_durations": {"early": 2.5, "normal": 3.0, "late": 2.5}, # Hours per slot
            "template_dates": {
                "early": "01-01-2024", 
                "normal": "02-01-2024", 
                "late": "03-01-2024"
            }
        }
    return profile

def update_user_profile(chat_id: str, profile_data: dict):
    users_collection.update_one(
        {"chat_id": str(chat_id)},
        {"$set": {"profile": profile_data}},
        upsert=True
    )