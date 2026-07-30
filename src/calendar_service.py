# ==========================================
# IMPORTS: Bringing in the necessary tools
# ==========================================
import datetime
import time
import pytz
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import config
from src.database import get_user_token, get_user_profile, update_user_profile, delete_user_token

# SCOPES define exactly what we are allowed to do with the user's Google account.
# In this case, we need full read/write access to their calendar.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Set up the timezone based on the config file (e.g., Asia/Kolkata)
tz = pytz.timezone(config.USER_TIMEZONE)

# Custom Error Class to easily catch when a user's token is invalid or expired
class AuthError(Exception): pass

# ==========================================
# AUTHENTICATION & CONNECTION
# ==========================================
def get_calendar_service(chat_id: str):
    """
    Takes the user's chat_id, finds their Google token in MongoDB, 
    and builds the 'service' object which is used to talk to Google Calendar.
    """
    token_dict = get_user_token(chat_id)
    if not token_dict: 
        raise AuthError("Not Authenticated")
    
    # Create the Google Credentials object using the dictionary from MongoDB
    creds = Credentials(**token_dict)
    
    try:
        # Build the actual connection to Google Calendar
        service = build('calendar', 'v3', credentials=creds)
        # We do a tiny test request (list 1 calendar) to make sure the token isn't dead
        service.calendarList().list(maxResults=1).execute()
        return service
    except RefreshError:
        # If Google says the refresh token is dead, we delete it and force a re-login
        delete_user_token(chat_id)
        raise AuthError("Token Revoked")
    except Exception as e:
        # Catch any other authorization errors (like if the user manually revoked app access)
        if "invalid_grant" in str(e).lower() or "unauthorized" in str(e).lower():
            delete_user_token(chat_id)
            raise AuthError("Token Revoked")
        raise e

# ==========================================
# TIME MATH HELPER
# ==========================================
def get_next_quarter_hour(dt: datetime.datetime):
    """
    Rounds the current time UP to the next 15-minute mark.
    Example: 07:05 becomes 07:15. 08:31 becomes 08:45.
    """
    minutes_to_add = 15 - (dt.minute % 15)
    return dt + datetime.timedelta(minutes=minutes_to_add)

# ==========================================
# THE MASTER SCHEDULE (11-BLOCK TEMPLATE)
# ==========================================
# This is the exact blueprint of your ideal day. 
# offset_min = how many minutes after waking up the task starts.
# duration = how long the task lasts in minutes.
DEFAULT_ROUTINE_BLOCKS = [
    {"title": "Morning Walk, Bath, Breakfast", "offset_min": 0, "duration": 120, "colorId": "5", "desc": "Light exercise, stretching, yoga. Skip mental exhaustion before main work."},
    {"title": "Practice / Work / Output", "offset_min": 135, "duration": 225, "colorId": "3", "desc": "Active work block. Try, practice, and create. USE POMODORO."},
    {"title": "Eat, Rest", "offset_min": 360, "duration": 45, "colorId": "5", "desc": "Lunch/brunch, relaxing, hydration."},
    {"title": "Workout with 90 min Timer", "offset_min": 405, "duration": 75, "colorId": "8", "desc": "Interval timer. Drop workout when time ends to stay efficient."},
    {"title": "Calm down", "offset_min": 480, "duration": 30, "colorId": "5", "desc": "Shower, recovery, mental calm."},
    {"title": "Learn, Study, Improve", "offset_min": 510, "duration": 210, "colorId": "9", "desc": "Deep educational block. Study planned materials."},
    {"title": "WHATEVER", "offset_min": 720, "duration": 75, "colorId": "2", "desc": "Unstructured time. Avoid vices."},
    {"title": "Dinner", "offset_min": 795, "duration": 45, "colorId": "5", "desc": "Dinner, cleaning up, relaxing."},
    {"title": "Journal, Trackers, Shopping", "offset_min": 840, "duration": 60, "colorId": "10", "desc": "Reflection, habit tracking, essentials for tomorrow."},
    {"title": "Wind down", "offset_min": 900, "duration": 45, "colorId": "3", "desc": "Second bath, meditate, prep bed."}
]

# ==========================================
# FIRST-RUN INITIALIZATION
# ==========================================
def initialize_new_user(chat_id: str, service, bot_instance):
    """
    Runs only once per user. Calculates dates 60 days in the past, 
    saves those dates to MongoDB, and injects the Master Schedule into Google Calendar.
    """
    profile = get_user_profile(chat_id)
    today = datetime.datetime.now(tz).date()
    
    # Define the 3 target dates far in the past so they don't clutter the user's current week
    early_date = today - datetime.timedelta(days=60)
    normal_date = today - datetime.timedelta(days=59)
    late_date = today - datetime.timedelta(days=58)
    
    # Save these dates to the database profile
    profile['template_dates'] = {
        "early": early_date.strftime("%d-%m-%Y"),
        "normal": normal_date.strftime("%d-%m-%Y"),
        "late": late_date.strftime("%d-%m-%Y")
    }

    # Notify the user on Telegram
    bot_instance.send_message(
        chat_id, 
        f"🛠️ **Initializing Calendar Templates...**\nCreating 11-block routines on past dates:\n\n"
        f"• Early Template: `{profile['template_dates']['early']}`\n"
        f"• Normal Template: `{profile['template_dates']['normal']}`\n"
        f"• Late Template: `{profile['template_dates']['late']}`",
        parse_mode="Markdown"
    )

    # Loop through Early, Normal, and Late, and paste the blocks onto those specific dates
    for key, date_str in profile['template_dates'].items():
        base_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
        # Assume the template starts at exactly 05:00 AM on the template day
        base_dt = tz.localize(datetime.datetime.combine(base_date, datetime.time(5, 0)))
        
        for block in DEFAULT_ROUTINE_BLOCKS:
            start_dt = base_dt + datetime.timedelta(minutes=block['offset_min'])
            end_dt = start_dt + datetime.timedelta(minutes=block['duration'])
            
            summary = block['title']
            # Small modification for Late Mode
            if key == "late" and "Walk" in summary: 
                summary = "⏰ " + summary + " (Late Mode)"

            # Construct the Google Calendar event payload
            event = {
                'summary': summary, 'description': block['desc'],
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'colorId': block['colorId']
            }
            # Fire it to Google!
            service.events().insert(calendarId='primary', body=event).execute()
            time.sleep(0.2) # Sleep briefly so Google doesn't block us for spamming
            
    # Mark user as initialized so we don't run this again
    profile['is_initialized'] = True
    update_user_profile(chat_id, profile)
    bot_instance.send_message(chat_id, "✅ **Templates Injected!** You can customize those dates directly in Google Calendar anytime.")

# ==========================================
# DYNAMIC TEMPLATE MATCHER
# ==========================================
def determine_dynamic_template(target_time: datetime.time, profile: dict):
    """
    Looks at the time the user woke up and compares it against their Wake Windows
    to decide if this is an Early, Normal, or Late start.
    """
    windows = profile.get('wake_windows', {})
    t_early = datetime.datetime.strptime(windows.get('earliest_start', '04:00'), "%H:%M").time()
    t_normal = datetime.datetime.strptime(windows.get('normal_start', '07:00'), "%H:%M").time()
    t_late = datetime.datetime.strptime(windows.get('late_start', '10:00'), "%H:%M").time()
    t_end = datetime.datetime.strptime(windows.get('latest_end', '13:00'), "%H:%M").time()

    # If 24H mode is ON, and they used the "Plan" feature (which skips the manual menu), 
    # we just broadly map the 24 hours into 3 chunks as a fallback.
    if profile.get('mode_24h', False):
        if t_early <= target_time < t_normal: return "early", profile['template_dates']['early']
        elif t_normal <= target_time < t_late: return "normal", profile['template_dates']['normal']
        else: return "late", profile['template_dates']['late']

    # Standard Windows Mode (Checks if the wake time fits strictly inside the windows)
    if t_early <= target_time < t_normal:
        return "early", profile['template_dates']['early']
    elif t_normal <= target_time < t_late:
        return "normal", profile['template_dates']['normal']
    elif t_late <= target_time <= t_end:
        return "late", profile['template_dates']['late']
    
    # If they woke up outside their configured hours, return None to trigger an error message
    return None, None

# ==========================================
# CORE SCHEDULING ENGINE
# ==========================================
def execute_schedule_creation(chat_id: str, target_datetime: datetime.datetime, bot_instance):
    """
    The main brain. 
    1. Checks if the user is initialized.
    2. Figures out which template to use (Early/Normal/Late).
    3. Fetches the events from that template in the past.
    4. Pastes them into today starting at the next 15-minute mark.
    """
    try:
        service = get_calendar_service(chat_id)
        profile = get_user_profile(chat_id)
        
        # Check if they need factory templates generated
        if not profile.get('is_initialized', False) or not profile.get('template_dates'):
            initialize_new_user(chat_id, service, bot_instance)
            profile = get_user_profile(chat_id)

        # --- THE 24-HOUR MANUAL OVERRIDE CHECK ---
        # Did bot.py save a temporary manual choice (because 24-hour mode is active)?
        manual_override = profile.get('temp_manual_override')
        
        if manual_override:
            # If yes, bypass the math and just use their manual choice!
            template_key = manual_override
            template_date_str = profile['template_dates'].get(template_key)
            
            # CRITICAL: We must delete this temporary memory immediately 
            # so it doesn't accidentally affect their future /plan commands.
            del profile['temp_manual_override']
            update_user_profile(chat_id, profile)
        else:
            # If no manual override exists, calculate it normally based on the clock
            template_key, template_date_str = determine_dynamic_template(target_datetime.time(), profile)
        
        # If the math couldn't find a valid slot (and no override was provided)
        if not template_key:
            bot_instance.send_message(
                chat_id, 
                f"❌ Wake time `{target_datetime.strftime('%H:%M')}` is outside your allowed window ({profile['wake_windows']['earliest_start']} - {profile['wake_windows']['latest_end']}).\n\n"
                f"Enable 24H Mode or update your Wake Windows in ⚙️ Settings / Configure!",
                parse_mode="Markdown"
            )
            return

        # Figure out the exact minute we should start pasting today's events
        schedule_start_dt = get_next_quarter_hour(target_datetime)
        
        # Define the exact 24-hour period of the past Template Date
        source_date = datetime.datetime.strptime(template_date_str, "%d-%m-%Y").date()
        source_start_dt = tz.localize(datetime.datetime.combine(source_date, datetime.time.min))
        source_end_dt = source_start_dt + datetime.timedelta(hours=23, minutes=59)

        bot_instance.send_message(chat_id, f"🔍 Slot matched: *{template_key.upper()}*\nFetching template from `{template_date_str}`...", parse_mode="Markdown")

        # Fetch ALL events that exist on that past template date
        events_result = service.events().list(
            calendarId='primary', timeMin=source_start_dt.isoformat(), timeMax=source_end_dt.isoformat(), singleEvents=True, orderBy='startTime'
        ).execute()
        source_events = events_result.get('items', [])

        if not source_events:
            bot_instance.send_message(chat_id, f"⚠️ No events found on source date `{template_date_str}`! Add events to that date in Google Calendar.", parse_mode="Markdown")
            return

        # We look at the very first event of the template date to figure out the "time gap"
        # Example: If the template started at 5:00 AM, and we are starting today at 7:15 AM, the shift is +2 hours 15 mins.
        first_event_start = datetime.datetime.fromisoformat(source_events[0]['start'].get('dateTime', source_events[0]['start'].get('date')))
        time_shift = tz.localize(schedule_start_dt) - first_event_start

        bot_instance.send_message(chat_id, f"📝 Copying {len(source_events)} tasks starting at {schedule_start_dt.strftime('%I:%M %p')}...")

        # Loop through every event found in the past, shift its time forward, and paste it into today
        for event in source_events:
            orig_start = datetime.datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
            orig_end = datetime.datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
            
            new_event = {
                'summary': event.get('summary', 'Busy'),
                'description': event.get('description', ''),
                'start': {'dateTime': (orig_start + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': (orig_end + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
            }
            # Make sure we carry over the beautiful color coding!
            if 'colorId' in event: 
                new_event['colorId'] = event['colorId']
                
            service.events().insert(calendarId='primary', body=new_event).execute()
            time.sleep(0.2) # Polite delay for Google's API

        bot_instance.send_message(chat_id, f"✅ **Schedule Deployed!**\nFirst task begins at {schedule_start_dt.strftime('%I:%M %p')}.", parse_mode="Markdown")

    except AuthError:
        # If the Auth fails anywhere in this massive function, catch it gracefully here
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Google access expired or revoked. Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Error: {str(e)}")

# ==========================================
# SWEEP / CLEAR DAY FEATURE
# ==========================================
def clear_day_events(chat_id: str, target_date: datetime.date, bot_instance):
    """Fetches every single event on a given date and deletes it."""
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.min))
        end_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.max))
        
        # Grab the list of events
        events = service.events().list(calendarId='primary', timeMin=start_dt.isoformat(), timeMax=end_dt.isoformat(), singleEvents=True).execute().get('items', [])
        
        # Nuke them one by one
        for e in events:
            service.events().delete(calendarId='primary', eventId=e['id']).execute()
            time.sleep(0.15)
            
        bot_instance.send_message(chat_id, f"✅ Cleared {len(events)} events from {target_date.strftime('%b %d')}.")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to clear: {str(e)}")

# ==========================================
# ADD CUSTOM TASK FEATURE
# ==========================================
def add_custom_task(chat_id: str, target_date: datetime.date, name: str, start_time: datetime.time, duration_hours: float, bot_instance):
    """Injects a single, standalone task onto the calendar (highlighted in red)."""
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, start_time))
        end_dt = start_dt + datetime.timedelta(hours=duration_hours)
        
        event = {
            'summary': name,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'colorId': '11' # 11 is Tomato Red (Makes custom tasks pop visually)
        }
        service.events().insert(calendarId='primary', body=event).execute()
        bot_instance.send_message(chat_id, f"✅ Task *{name}* added to {target_date.strftime('%b %d')} at {start_time.strftime('%H:%M')}.", parse_mode="Markdown")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to add task: {str(e)}")