from pymongo import MongoClient
import config

# Connect to MongoDB
client = MongoClient(config.MONGO_URI)
db = client['vector_workflows']
users_collection = db['google_tokens']

def save_user_token(chat_id: str, token_dict: dict):
    """Saves or updates a user's Google OAuth token in MongoDB."""
    users_collection.update_one(
        {"chat_id": str(chat_id)},
        {"$set": {"token": token_dict}},
        upsert=True
    )

def get_user_token(chat_id: str) -> dict:
    """Retrieves a user's token from MongoDB."""
    user = users_collection.find_one({"chat_id": str(chat_id)})
    if user:
        return user.get("token")
    return None

def delete_user_token(chat_id: str):
    """Logs the user out by deleting their token."""
    users_collection.delete_one({"chat_id": str(chat_id)})