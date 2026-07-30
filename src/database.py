from pymongo import MongoClient
import config

client = MongoClient(config.MONGO_URI)
db = client['vector_workflows']
users_collection = db['google_tokens']

DEFAULT_PROFILE = {
    "is_initialized": False,
    "mode_24h": False,
    "wake_windows": {
        "earliest_start": "04:00",
        "normal_start": "07:00",
        "late_start": "10:00",
        "latest_end": "13:00"
    },
    "template_dates": {}
}

def save_user_token(chat_id: str, token_dict: dict):
    users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"token": token_dict}}, upsert=True)

def get_user_token(chat_id: str) -> dict:
    user = users_collection.find_one({"chat_id": str(chat_id)})
    return user.get("token") if user else None

def delete_user_token(chat_id: str):
    users_collection.update_one({"chat_id": str(chat_id)}, {"$unset": {"token": ""}})

def delete_user_data(chat_id: str):
    """Completely wipes user document from MongoDB (Full Account Deletion/Logout)."""
    users_collection.delete_one({"chat_id": str(chat_id)})

def get_user_profile(chat_id: str) -> dict:
    user = users_collection.find_one({"chat_id": str(chat_id)})
    profile = user.get("profile", {}) if user else {}
    
    if not profile:
        profile = DEFAULT_PROFILE.copy()
    else:
        if "wake_windows" not in profile:
            profile["wake_windows"] = DEFAULT_PROFILE["wake_windows"].copy()
        if "mode_24h" not in profile:
            profile["mode_24h"] = False
        if "is_initialized" not in profile:
            profile["is_initialized"] = False
        if "template_dates" not in profile:
            profile["template_dates"] = {}

    return profile

def update_user_profile(chat_id: str, profile_data: dict):
    users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile": profile_data}}, upsert=True)

def reset_user_profile(chat_id: str, target: str = "full"):
    if target == "full":
        users_collection.update_one({"chat_id": str(chat_id)}, {"$unset": {"profile": ""}})
    elif target == "windows":
        users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile.wake_windows": DEFAULT_PROFILE["wake_windows"]}})
    elif target == "templates":
        users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile.template_dates": {}, "profile.is_initialized": False}})