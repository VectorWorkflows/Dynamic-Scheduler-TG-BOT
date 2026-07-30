import os
import threading
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
import config
from src.bot import start_bot, bot
from src.database import save_user_token

# Allow HTTP for local testing
if "localhost" in config.BASE_URL or "127.0.0.1" in config.BASE_URL:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = FastAPI(title="Vector Workflows - OAuth Engine")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Vector Workflows"}

# --- Add this right below your SCOPES = [...] line ---
oauth_flows = {}  # Temporary memory to hold the login session

@app.get("/login")
def login(chat_id: str):
    """Generates the Google Sign-in screen for a specific user."""
    flow = Flow.from_client_secrets_file(str(config.CREDENTIALS_FILE_PATH), scopes=SCOPES)
    flow.redirect_uri = f"{config.BASE_URL}/callback"
    
    # Generate URL and State
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline', state=chat_id)
    
    # SAVE the exact flow instance in memory linked to their chat_id
    oauth_flows[chat_id] = flow
    
    return RedirectResponse(auth_url)

@app.get("/callback")
def oauth_callback(state: str, request: Request):
    """Google redirects here after the user clicks 'Allow'."""
    try:
        chat_id = state
        
        # RETRIEVE the exact flow we created in /login (It contains the secret code_verifier!)
        flow = oauth_flows.get(chat_id)
        
        if not flow:
            return HTMLResponse("<h1>❌ Session Expired</h1><p>Please go back to Telegram, send /menu, and click the link again.</p>")
            
        # Exchange the URL response for the secure tokens
        flow.fetch_token(authorization_response=str(request.url))
        creds = flow.credentials
        
        # Format for database
        token_dict = {
            'token': creds.token, 'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri, 'client_id': creds.client_id,
            'client_secret': creds.client_secret, 'scopes': creds.scopes
        }
        
        # Save to MongoDB
        save_user_token(chat_id, token_dict)
        
        # Clean up memory
        del oauth_flows[chat_id]
        
        bot.send_message(chat_id, "✅ **Google Calendar Connected Successfully!**\n\nSend /menu to start scheduling.", parse_mode="Markdown")
        
        return HTMLResponse("<h1>✅ Authentication Successful!</h1><p>You can close this tab and return to Telegram.</p>")
        
    except Exception as e:
        return HTMLResponse(f"<h1>❌ OAuth Error</h1><p>{str(e)}</p>")


def launch_bot_thread():
    try:
        start_bot()
    except Exception as e:
        print(f"[CRITICAL] Bot crashed: {e}")

if __name__ == "__main__":
    bot_thread = threading.Thread(target=launch_bot_thread, daemon=True)
    bot_thread.start()
    
    port = int(os.getenv("PORT", config.PORT))
    print(f"🌐 FastAPI Web Server running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)