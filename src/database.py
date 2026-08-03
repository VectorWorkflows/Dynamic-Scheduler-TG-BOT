# ==========================================
# DATABASE CONNECTION SETUP
# ==========================================
# This section connects your bot to the MongoDB database where all user data is safely stored.
from pymongo import MongoClient
import config

# 'client' acts as the bridge to your database using the URI link in your .env file.
client = MongoClient(config.MONGO_URI)
# 'db' selects the specific database workspace we named 'vector_workflows'.
db = client['vector_workflows']
# 'users_collection' is like a specific filing cabinet inside that workspace just for user data.
users_collection = db['google_tokens']

# ==========================================
# DEFAULT USER SETTINGS (MANAGER CUSTOMIZATION ZONE)
# ==========================================
# MANAGER NOTE: If a brand new user joins the bot, these are the exact settings they get by default.
# You can change the "04:00" times here to change what the bot considers a "normal" default globally.
DEFAULT_PROFILE = {
    "mode_24h": False,
    "wake_windows": {
        "earliest_start": "04:00", # Default time the 'Early' slot begins
        "normal_start": "07:00",   # Default time the 'Normal' slot begins
        "late_start": "10:00",     # Default time the 'Late' slot begins
        "latest_end": "13:00"      # The absolute latest wake time allowed (unless 24H mode is ON)
    },
    "custom_templates": {} # This stays empty by default. It fills up only if a user captures a custom 18-hour day.
}

# ==========================================
# GOOGLE TOKEN MANAGEMENT (THE DIGITAL KEYS)
# ==========================================

def save_user_token(chat_id: str, token_dict: dict):
    # Saves the user's Google login key to the database so they don't have to login every day.
    users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"token": token_dict}}, upsert=True)

def get_user_token(chat_id: str) -> dict:
    # Retrieves the user's Google login key when the bot needs permission to edit their calendar.
    user = users_collection.find_one({"chat_id": str(chat_id)})
    return user.get("token") if user else None

def delete_user_token(chat_id: str):
    # Simply removes the Google login key (like logging out of Google), but keeps their profile settings intact.
    users_collection.update_one({"chat_id": str(chat_id)}, {"$unset": {"token": ""}})

def delete_user_data(chat_id: str):
    """Completely wipes user document from MongoDB (Full Account Deletion/Logout)."""
    # This is the "Nuclear Option". It completely deletes the user from our filing cabinet forever.
    users_collection.delete_one({"chat_id": str(chat_id)})

# ==========================================
# USER PROFILE MANAGEMENT (SETTINGS & PREFERENCES)
# ==========================================

def get_user_profile(chat_id: str) -> dict:
    # Grabs the user's custom settings (like their personal wake windows or 24H mode status).
    user = users_collection.find_one({"chat_id": str(chat_id)})
    profile = user.get("profile", {}) if user else {}
    
    # DEFENSIVE HEALING: If the user is brand new, or if we added new features to the bot and their 
    # old profile is missing pieces, this safely patches their profile with the default settings above so the bot never crashes.
    if not profile:
        profile = DEFAULT_PROFILE.copy()
    else:
        if "wake_windows" not in profile:
            profile["wake_windows"] = DEFAULT_PROFILE["wake_windows"].copy()
        if "mode_24h" not in profile:
            profile["mode_24h"] = False
        # Ensures the user has a memory bucket for custom JSON templates
        if "custom_templates" not in profile:
            profile["custom_templates"] = {}

    return profile

def update_user_profile(chat_id: str, profile_data: dict):
    # Whenever a user clicks a button in Telegram to change a setting, this saves that change permanently to the database.
    users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile": profile_data}}, upsert=True)

def reset_user_profile(chat_id: str, target: str = "full"):
    # The 'Reset Settings' logic. It allows us to wipe specific parts of a user's memory via the Settings Menu.
    if target == "full":
        # Wipes ALL settings. The bot will fall back to templates.json and default wake windows.
        users_collection.update_one({"chat_id": str(chat_id)}, {"$unset": {"profile": ""}})
    elif target == "windows":
        # Only resets their custom Early/Normal/Late wake window times back to the defaults set at the top of this file.
        users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile.wake_windows": DEFAULT_PROFILE["wake_windows"]}})
    elif target == "templates":
        # Wipes their custom 18-hour memory blocks so the bot falls back to the master templates.json file.
        users_collection.update_one({"chat_id": str(chat_id)}, {"$set": {"profile.custom_templates": {}}})