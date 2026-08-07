# ==========================================
# IMPORTS: Bringing in the necessary tools
# ==========================================
# We import web server tools (FastAPI, uvicorn), background workers (threading),
# Google's security tools (Flow), and our own bot logic and database files.
import os
import threading
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
import config
from src.bot import start_bot, bot
from src.database import save_user_token

# ==========================================
# LOCAL TESTING CONFIGURATION
# ==========================================
# Google's security system usually blocks any login attempts that don't use a secure 'https://' connection.
# This block tells Google to relax its rules if we are testing the bot on our own computer (localhost).
# Allow HTTP for local testing
if "localhost" in config.BASE_URL or "127.0.0.1" in config.BASE_URL:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# Initialize our web server. This acts as the "Drive-Thru Window" listening for Google's responses.
app = FastAPI(title="Vector Workflows - OAuth Engine")
# SCOPES define the permissions we are asking the user for (Full access to their Google Calendar).
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ==========================================
# SESSION MEMORY (THE VAULT)
# ==========================================
# When a user clicks "Login", they leave Telegram and go to Google. 
# We need a temporary place to remember who they are while they are gone.
# THE VAULT: We now store the ENTIRE Flow object here. 
# This preserves the native PKCE secrets and OAuth session perfectly.
flow_store = {}

# ==========================================
# WEB SERVER ROUTES
# ==========================================

# A simple diagnostic route. If you visit your website's /health page, it just says "I am alive."
@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "healthy", "service": "Vector Workflows"}

# This is where the user is sent when they click the login link in Telegram.
@app.get("/login")
def login(chat_id: str):
    # 1. Create the flow object
    # We load our digital ID card (credentials.json) to prove to Google who we are.
    flow = Flow.from_client_secrets_file(str(config.CREDENTIALS_FILE_PATH), scopes=SCOPES)
    flow.redirect_uri = f"{config.BASE_URL}/callback"
    
    # 2. Generate the auth url and Google's internal PKCE challenge
    # We create the exact Google webpage link the user needs to see to click "Allow".
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline', state=chat_id)
    
    # 3. SECURE FIX: Store the *living object* in memory to prevent session wipe
    # We lock their session in the vault using their Telegram Chat ID as the key.
    flow_store[chat_id] = flow
    
    # Send the user to the Google Login page.
    return RedirectResponse(auth_url)

# This is where Google automatically sends the user AFTER they click "Allow".
@app.get("/callback")
def oauth_callback(state: str, request: Request):
    try:
        # The 'state' is the user's Telegram Chat ID that we passed to Google earlier.
        chat_id = state
        
        # 1. SECURE FIX: Retrieve the EXACT flow object that generated the link
        # We check the vault. If they took too long or the server restarted, we show an error.
        if chat_id not in flow_store:
            return HTMLResponse(
                "<h1 style='color: #c62828; text-align: center; margin-top: 50px;'>❌ Session Expired</h1>"
                "<p style='text-align: center;'>Please go back to Telegram and click the login link again.</p>"
            )
            
        # Pull their active session out of the vault
        flow = flow_store[chat_id]
        
        # 2. Intercept and fix Render.com's HTTP Proxy Downgrade bug
        # Cloud hosts like Render sometimes scramble 'https' to 'http' internally. This manually forces it back so Google doesn't panic.
        auth_response_url = str(request.url)
        if "https://" in config.BASE_URL and auth_response_url.startswith("http://"):
            auth_response_url = auth_response_url.replace("http://", "https://", 1)
            
        # 3. Fetch the token (This will now flawlessly use the native PKCE secrets inside the object)
        # We trade the one-time code Google just gave us for a permanent access token.
        flow.fetch_token(authorization_response=auth_response_url)
        creds = flow.credentials
        
        # Clean up the vault to save memory since we have the token now.
        del flow_store[chat_id]
        
        # Package the keys into a neat dictionary
        token_dict = {
            'token': creds.token, 'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri, 'client_id': creds.client_id,
            'client_secret': creds.client_secret, 'scopes': creds.scopes
        }
        
        # Save the keys to MongoDB permanently
        save_user_token(chat_id, token_dict)
        # Ping the user on Telegram to let them know it worked!
        bot.send_message(chat_id, "✅ **Google Calendar Connected Successfully!**\n\nTap /menu to start scheduling.", parse_mode="Markdown")
        
        # Show a pretty success page in their web browser
        return HTMLResponse("""
            <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                <h1 style="color: #2e7d32;">✅ Authentication Successful!</h1>
                <p style="font-size: 18px;">Your Google Calendar is now linked to Vector Workflows.</p>
                <p style="font-size: 16px; color: #555;">You can close this tab and return to Telegram.</p>
            </div>
        """)
        
    except Exception as e:
        # If absolutely anything goes wrong during login, show this error page instead of crashing the server.
        return HTMLResponse(f"""
            <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                <h1 style="color: #c62828;">❌ OAuth Error</h1>
                <p>{str(e)}</p>
                <p style="font-size: 12px; color: #888;">If this persists, tap ⚙️ Settings -> Reset / Logout in Telegram.</p>
            </div>
        """)

# ==========================================
# SERVER LAUNCH SEQUENCE
# ==========================================

def launch_bot_thread():
    # This function acts as a wrapper to keep the Telegram bot running constantly.
    try:
        start_bot()
    except Exception as e:
        print(f"[CRITICAL] Bot crashed: {e}")

# This block is the true starting point of the entire application when you run 'python main.py'
if __name__ == "__main__":
    # We must run TWO things at once: The Telegram Bot and the Web Server.
    # We put the Telegram Bot on a "background thread" (like a co-worker doing tasks in the background).
    bot_thread = threading.Thread(target=launch_bot_thread, daemon=True)
    bot_thread.start()
    
    # We launch the Web Server on the main thread so it listens for web traffic from Google.
    port = int(os.getenv("PORT", str(config.PORT)))
    print(f"🌐 FastAPI Web Server running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)