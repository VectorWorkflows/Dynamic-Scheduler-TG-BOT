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
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

app = FastAPI(title="Vector Workflows - OAuth Engine")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# THE VAULT: We now store the ENTIRE Flow object here. 
# This preserves the native PKCE secrets and OAuth session perfectly.
flow_store = {}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Vector Workflows"}

@app.get("/login")
def login(chat_id: str):
    # 1. Create the flow object
    flow = Flow.from_client_secrets_file(str(config.CREDENTIALS_FILE_PATH), scopes=SCOPES)
    flow.redirect_uri = f"{config.BASE_URL}/callback"
    
    # 2. Generate the auth url and Google's internal PKCE challenge
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline', state=chat_id)
    
    # 3. SECURE FIX: Store the *living object* in memory to prevent session wipe
    flow_store[chat_id] = flow
    
    return RedirectResponse(auth_url)

@app.get("/callback")
def oauth_callback(state: str, request: Request):
    try:
        chat_id = state
        
        # 1. SECURE FIX: Retrieve the EXACT flow object that generated the link
        if chat_id not in flow_store:
            return HTMLResponse(
                "<h1 style='color: #c62828; text-align: center; margin-top: 50px;'>❌ Session Expired</h1>"
                "<p style='text-align: center;'>Please go back to Telegram and click the login link again.</p>"
            )
            
        flow = flow_store[chat_id]
        
        # 2. Intercept and fix Render.com's HTTP Proxy Downgrade bug
        auth_response_url = str(request.url)
        if "https://" in config.BASE_URL and auth_response_url.startswith("http://"):
            auth_response_url = auth_response_url.replace("http://", "https://", 1)
            
        # 3. Fetch the token (This will now flawlessly use the native PKCE secrets inside the object)
        flow.fetch_token(authorization_response=auth_response_url)
        creds = flow.credentials
        
        # Clean up the vault to save memory
        del flow_store[chat_id]
        
        token_dict = {
            'token': creds.token, 'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri, 'client_id': creds.client_id,
            'client_secret': creds.client_secret, 'scopes': creds.scopes
        }
        
        save_user_token(chat_id, token_dict)
        bot.send_message(chat_id, "✅ **Google Calendar Connected Successfully!**\n\nTap /menu to start scheduling.", parse_mode="Markdown")
        
        return HTMLResponse("""
            <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                <h1 style="color: #2e7d32;">✅ Authentication Successful!</h1>
                <p style="font-size: 18px;">Your Google Calendar is now linked to Vector Workflows.</p>
                <p style="font-size: 16px; color: #555;">You can close this tab and return to Telegram.</p>
            </div>
        """)
        
    except Exception as e:
        return HTMLResponse(f"""
            <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                <h1 style="color: #c62828;">❌ OAuth Error</h1>
                <p>{str(e)}</p>
                <p style="font-size: 12px; color: #888;">If this persists, tap ⚙️ Settings -> Reset / Logout in Telegram.</p>
            </div>
        """)

def launch_bot_thread():
    try:
        start_bot()
    except Exception as e:
        print(f"[CRITICAL] Bot crashed: {e}")

if __name__ == "__main__":
    bot_thread = threading.Thread(target=launch_bot_thread, daemon=True)
    bot_thread.start()
    
    port = int(os.getenv("PORT", str(config.PORT)))
    print(f"🌐 FastAPI Web Server running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)