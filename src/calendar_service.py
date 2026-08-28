# ==========================================
# IMPORTS: Bringing in the necessary tools
# ==========================================
import datetime
import time
import json
import os
import pytz
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import config
from src.database import get_user_token, get_user_profile, update_user_profile, delete_user_token

# SCOPES define exactly what we are allowed to do with the user's Google account.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

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
    
    creds = Credentials(**token_dict)
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        service.calendarList().list(maxResults=1).execute()
        return service
    except RefreshError:
        delete_user_token(chat_id)
        raise AuthError("Token Revoked")
    except Exception as e:
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
# DYNAMIC TEMPLATE MATCHER
# ==========================================
def determine_dynamic_template(target_time: datetime.time, profile: dict):
    """
    Looks at the time the user woke up and compares it against their Wake Windows
    to decide if this is an Early, Normal, or Late start.
    Now simply returns the string name of the slot.
    """
    windows = profile.get('wake_windows', {})
    t_early = datetime.datetime.strptime(windows.get('earliest_start', '04:00'), "%H:%M").time()
    t_normal = datetime.datetime.strptime(windows.get('normal_start', '07:00'), "%H:%M").time()
    t_late = datetime.datetime.strptime(windows.get('late_start', '10:00'), "%H:%M").time()
    t_end = datetime.datetime.strptime(windows.get('latest_end', '13:00'), "%H:%M").time()

    if profile.get('mode_24h', False):
        if t_early <= target_time < t_normal: return "early"
        elif t_normal <= target_time < t_late: return "normal"
        else: return "late"

    if t_early <= target_time < t_normal: return "early"
    elif t_normal <= target_time < t_late: return "normal"
    elif t_late <= target_time <= t_end: return "late"
    
    return None

# ==========================================
# CORE SCHEDULING ENGINE (MEMORY-OPTIMIZED)
# ==========================================
def execute_schedule_creation(chat_id: str, target_datetime: datetime.datetime, bot_instance):
    """
    The lightning-fast main brain. 
    1. Figures out which template to use (Early/Normal/Late).
    2. Loads the events directly from memory (templates.json or MongoDB).
    3. Calculates the time shift based on the first event.
    4. Pastes them directly into today.
    """
    try:
        service = get_calendar_service(chat_id)
        profile = get_user_profile(chat_id)

        # --- MANUAL OVERRIDE CHECK ---
        manual_override = profile.get('temp_manual_override')
        
        if manual_override:
            template_key = manual_override
            del profile['temp_manual_override']
            update_user_profile(chat_id, profile)
        else:
            template_key = determine_dynamic_template(target_datetime.time(), profile)
        
        if not template_key:
            bot_instance.send_message(
                chat_id, 
                f"❌ Wake time `{target_datetime.strftime('%H:%M')}` is outside your allowed window.\n\n"
                f"Enable 24H Mode or update your Wake Windows in ⚙️ Settings!",
                parse_mode="Markdown"
            )
            return

        bot_instance.send_message(chat_id, f"🔍 Slot matched: *{template_key.upper()}*\nLoading template from memory...", parse_mode="Markdown")

        # --- LOAD FROM MEMORY (ZERO API CALLS!) ---
        source_events = []
        
        # First, check if the user has a custom template saved in their database profile
        custom_templates = profile.get('custom_templates', {})
        if template_key in custom_templates and len(custom_templates[template_key]) > 0:
            source_events = custom_templates[template_key]
        else:
            # If no custom DB template exists, load from our bulletproof templates.json file
            if os.path.exists("templates.json"):
                with open("templates.json", "r") as f:
                    all_local_templates = json.load(f)
                    source_events = all_local_templates.get(template_key, [])
            
        if not source_events:
            bot_instance.send_message(chat_id, f"⚠️ No tasks found in memory for the {template_key.upper()} slot! Check your templates.json file.")
            return

        # Figure out the exact minute we should start pasting today's events
        schedule_start_dt = get_next_quarter_hour(target_datetime)

        # We look at the very first event in the JSON to figure out the "time gap"
        first_event_start_str = source_events[0]['start_time']
        first_event_start = datetime.datetime.fromisoformat(first_event_start_str)
        if not first_event_start.tzinfo:
            first_event_start = tz.localize(first_event_start)
        else:
            first_event_start = first_event_start.astimezone(tz)
            
        time_shift = tz.localize(schedule_start_dt.replace(tzinfo=None)) - first_event_start

        bot_instance.send_message(chat_id, f"📝 Injecting {len(source_events)} tasks starting at {schedule_start_dt.strftime('%I:%M %p')}...")

        # Loop through every event in memory, shift its time forward, and paste it to Google
        for event_data in source_events:
            orig_start = datetime.datetime.fromisoformat(event_data['start_time'])
            orig_end = datetime.datetime.fromisoformat(event_data['end_time'])
            
            if not orig_start.tzinfo: orig_start = tz.localize(orig_start)
            if not orig_end.tzinfo: orig_end = tz.localize(orig_end)
            
            new_event = {
                'summary': event_data['summary'],
                'description': event_data.get('description', ''),
                'start': {'dateTime': (orig_start + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': (orig_end + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
                'colorId': event_data.get('colorId', '5')
            }
            service.events().insert(calendarId='primary', body=new_event).execute()
            time.sleep(0.2) # Polite delay for Google's API

        bot_instance.send_message(chat_id, f"✅ **Schedule Deployed!**\nFirst task begins at {schedule_start_dt.strftime('%I:%M %p')}.", parse_mode="Markdown")

    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Google access expired or revoked. Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Error: {str(e)}")

# ==========================================
# 18-HOUR SMART CUSTOM TEMPLATE FETCHER
# ==========================================
def fetch_and_save_custom_template(chat_id: str, slot: str, date_str: str, bot_instance):
    """
    Grabs an 18-hour block of tasks from a specific custom date and saves it 
    directly to the user's MongoDB profile as JSON memory!
    """
    try:
        service = get_calendar_service(chat_id)
        profile = get_user_profile(chat_id)
        
        bot_instance.send_message(chat_id, f"📡 Scanning Google Calendar for your custom schedule on `{date_str}`...", parse_mode="Markdown")
        
        # 1. Look at the whole day to find the very first task
        base_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
        day_start = tz.localize(datetime.datetime.combine(base_date, datetime.time.min))
        day_end = tz.localize(datetime.datetime.combine(base_date, datetime.time.max))
        
        initial_events = service.events().list(
            calendarId='primary', timeMin=day_start.isoformat(), timeMax=day_end.isoformat(), 
            singleEvents=True, orderBy='startTime', maxResults=1
        ).execute().get('items', [])
        
        if not initial_events:
            bot_instance.send_message(chat_id, f"⚠️ I couldn't find any tasks on `{date_str}`. Please add events to Google Calendar and try again.", parse_mode="Markdown")
            return
            
        # 2. Find the exact start time of that first task
        first_event_str = initial_events[0]['start'].get('dateTime', initial_events[0]['start'].get('date'))
        first_event_dt = datetime.datetime.fromisoformat(first_event_str)
        if not first_event_dt.tzinfo: first_event_dt = tz.localize(first_event_dt)
        
        # 3. Create a smart 18-hour capture window starting from that exact moment
        capture_end_dt = first_event_dt + datetime.timedelta(hours=18)
        
        bot_instance.send_message(chat_id, f"🔍 Found first task at {first_event_dt.strftime('%I:%M %p')}. Capturing the next 18 hours...")
        
        full_events = service.events().list(
            calendarId='primary', timeMin=first_event_dt.isoformat(), timeMax=capture_end_dt.isoformat(), 
            singleEvents=True, orderBy='startTime', maxResults=50
        ).execute().get('items', [])
        
        # 4. Clean the events and prep them for database storage
        cleaned_events = []
        for e in full_events:
            cleaned_events.append({
                "summary": e.get('summary', 'Busy'),
                "description": e.get('description', ''),
                "start_time": e['start'].get('dateTime', e['start'].get('date')),
                "end_time": e['end'].get('dateTime', e['end'].get('date')),
                "colorId": e.get('colorId', '5')
            })
            
        # 5. Save directly to MongoDB memory
        if 'custom_templates' not in profile:
            profile['custom_templates'] = {}
            
        profile['custom_templates'][slot] = cleaned_events
        update_user_profile(chat_id, profile)
        
        bot_instance.send_message(chat_id, f"✅ **Success!** Captured {len(cleaned_events)} tasks.\nThey are now saved in memory for your **{slot.upper()}** template.", parse_mode="Markdown")
        
    except AuthError:
        bot_instance.send_message(chat_id, f"🔒 Google access expired. Please log in again:\n\n{config.BASE_URL}/login?chat_id={chat_id}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to fetch template: {str(e)}")

# ==========================================
# SWEEP / CLEAR DAY FEATURE
# ==========================================
def clear_day_events(chat_id: str, target_date: datetime.date, bot_instance):
    """Fetches every single event on a given date and deletes it."""
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.min))
        end_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.max))
        
        events = service.events().list(calendarId='primary', timeMin=start_dt.isoformat(), timeMax=end_dt.isoformat(), singleEvents=True).execute().get('items', [])
        
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
            'colorId': '11' # 11 is Tomato Red
        }
        service.events().insert(calendarId='primary', body=event).execute()
        bot_instance.send_message(chat_id, f"✅ Task *{name}* added to {target_date.strftime('%b %d')} at {start_time.strftime('%H:%M')}.", parse_mode="Markdown")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to add task: {str(e)}")