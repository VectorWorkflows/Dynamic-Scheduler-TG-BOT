import datetime
import time
import pytz
from typing import Dict, Any
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import config
from src.database import get_user_token, get_user_profile, update_user_profile, delete_user_token

SCOPES = ["https://www.googleapis.com/auth/calendar"]
tz = pytz.timezone(config.USER_TIMEZONE)

class AuthError(Exception):
    pass

def get_calendar_service(chat_id: str):
    token_dict = get_user_token(chat_id)
    if not token_dict:
        raise AuthError("Not Authenticated")
    
    creds = Credentials(
        token=token_dict.get('token'),
        refresh_token=token_dict.get('refresh_token'),
        token_uri=token_dict.get('token_uri'),
        client_id=token_dict.get('client_id'),
        client_secret=token_dict.get('client_secret'),
        scopes=SCOPES
    )
    
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

def get_next_quarter_hour(dt: datetime.datetime):
    minutes_to_add = 15 - (dt.minute % 15)
    return dt + datetime.timedelta(minutes=minutes_to_add)

# MASTER DEFAULT ROUTINE (16-Hour Baseline Template)
DEFAULT_ROUTINE_BLOCKS = [
    {
        "title": "Morning Walk, Bath, Breakfast",
        "offset_start_min": 0,
        "duration_min": 120,
        "colorId": "5", # Yellow
        "description": "Light exercise, stretching, yoga. Skip mental exhaustion before main work. Move to next task when done."
    },
    {
        "title": "Practice / Work / Output",
        "offset_start_min": 135, # 02:15 offset
        "duration_min": 225, # 3h 45m
        "colorId": "3", # Purple
        "description": "Active work block. Try, practice, and create something yourself. USE POMODORO TO AVOID BEING DISTRACTED."
    },
    {
        "title": "Eat, Rest",
        "offset_start_min": 360, # 06:00 offset
        "duration_min": 45,
        "colorId": "5", # Yellow
        "description": "Lunch or brunch, relaxing, hydration, stretching, phone break before exercise."
    },
    {
        "title": "Workout with 90 min Timer",
        "offset_start_min": 405, # 06:45 offset
        "duration_min": 75,
        "colorId": "8", # Gray
        "description": "Use interval timer for workouts. Drop workout when time ends to stay efficient."
    },
    {
        "title": "Calm down",
        "offset_start_min": 480, # 08:00 offset
        "duration_min": 30,
        "colorId": "5", # Yellow
        "description": "Shower, recovery, stretching, breathing, cooling body temperature and mental state."
    },
    {
        "title": "Learn, Study, Improve",
        "offset_start_min": 510, # 08:30 offset
        "duration_min": 210, # 3h 30m
        "colorId": "9", # Blue
        "description": "Deep educational block. Study planned playlists, books, courses, or concepts needed for work."
    },
    {
        "title": "WHATEVER",
        "offset_start_min": 720, # 12:00 offset
        "duration_min": 75, # 1h 15m
        "colorId": "2", # Green
        "description": "Unstructured time: meet friends, play sports, games, typing practice. Avoid vices/addictions."
    },
    {
        "title": "Dinner",
        "offset_start_min": 795, # 13:15 offset
        "duration_min": 45,
        "colorId": "5", # Yellow
        "description": "Dinner, cleaning up, relaxing."
    },
    {
        "title": "Journal, Trackers, Shopping",
        "offset_start_min": 840, # 14:00 offset
        "duration_min": 60,
        "colorId": "10", # Teal / Basil
        "description": "Daily reflection, habit/mood tracking, pick up essentials/groceries for tomorrow."
    },
    {
        "title": "Wind down",
        "offset_start_min": 900, # 15:00 offset
        "duration_min": 45,
        "colorId": "3", # Purple
        "description": "Second bath, natural meditation, prep bed, read physical book. Lay down without moving if awake."
    }
]

def initialize_new_user(chat_id: str, service):
    """Pastes the 16-hour default master routine onto 3 past template dates in Google Calendar."""
    profile = get_user_profile(chat_id)
    
    for key, date_str in profile['template_dates'].items():
        base_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
        base_dt = tz.localize(datetime.datetime.combine(base_date, datetime.time(5, 0))) # Base starts at 05:00 AM
        
        for block in DEFAULT_ROUTINE_BLOCKS:
            start_dt = base_dt + datetime.timedelta(minutes=block['offset_start_min'])
            end_dt = start_dt + datetime.timedelta(minutes=block['duration_min'])
            
            summary = block['title']
            if key == "late" and "walk" in summary.lower():
                summary = "⏰ " + summary + " (Late Mode: Keep Quick)"

            event = {
                'summary': summary,
                'description': block['description'],
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'colorId': block['colorId']
            }
            service.events().insert(calendarId='primary', body=event).execute()
            time.sleep(0.2)
            
    profile['is_initialized'] = True
    update_user_profile(chat_id, profile)

def determine_dynamic_template(target_time: datetime.time, profile: dict):
    """Calculates whether a wake time is Early, Normal, or Late based on custom slots or 24h mode."""
    if profile.get('mode_24h', False):
        # In 24h mode: 04:00-12:00 = Early, 12:00-20:00 = Normal, 20:00-04:00 = Late
        hour = target_time.hour
        if 4 <= hour < 12:
            return "early", profile['template_dates']['early']
        elif 12 <= hour < 20:
            return "normal", profile['template_dates']['normal']
        else:
            return "late", profile['template_dates']['late']

    # Standard / Custom Slot Mode
    now = datetime.datetime.now()
    earliest_dt = datetime.datetime.strptime(profile['wake_window']['earliest'], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    
    durations = profile.get('slot_durations', {"early": 2.5, "normal": 3.0, "late": 2.5})
    early_dur = datetime.timedelta(hours=durations['early'])
    normal_dur = datetime.timedelta(hours=durations['normal'])
    
    normal_start_dt = earliest_dt + early_dur
    late_start_dt = normal_start_dt + normal_dur
    
    target_dt = datetime.datetime.combine(now.date(), target_time)
    
    if earliest_dt <= target_dt < normal_start_dt:
        return "early", profile['template_dates']['early']
    elif normal_start_dt <= target_dt < late_start_dt:
        return "normal", profile['template_dates']['normal']
    else:
        return "late", profile['template_dates']['late']

def execute_schedule_creation(chat_id: str, target_datetime: datetime.datetime, bot_instance):
    try:
        service = get_calendar_service(chat_id)
        profile = get_user_profile(chat_id)
        
        if not profile.get('is_initialized', False):
            bot_instance.send_message(chat_id, "⚙️ Generating default master routine templates in your calendar... This takes ~10 seconds.")
            initialize_new_user(chat_id, service)
            profile = get_user_profile(chat_id)

        template_key, template_date_str = determine_dynamic_template(target_datetime.time(), profile)
        schedule_start_dt = get_next_quarter_hour(target_datetime)
        
        source_date = datetime.datetime.strptime(template_date_str, "%d-%m-%Y").date()
        source_start_dt = tz.localize(datetime.datetime.combine(source_date, datetime.time.min))
        source_end_dt = source_start_dt + datetime.timedelta(hours=23, minutes=59)

        bot_instance.send_message(chat_id, f"🔍 Found slot: *{template_key.upper()}*\nFetching template from {template_date_str}...", parse_mode="Markdown")

        events_result = service.events().list(
            calendarId='primary', timeMin=source_start_dt.isoformat(), 
            timeMax=source_end_dt.isoformat(), singleEvents=True, orderBy='startTime'
        ).execute()
        source_events = events_result.get('items', [])

        if not source_events:
            bot_instance.send_message(chat_id, f"⚠️ No events found on template date ({template_date_str})! Open Google Calendar, add tasks to that date, and try again.")
            return

        first_event_start = datetime.datetime.fromisoformat(source_events[0]['start'].get('dateTime', source_events[0]['start'].get('date')))
        time_shift = tz.localize(schedule_start_dt) - first_event_start

        bot_instance.send_message(chat_id, f"📝 Copying {len(source_events)} tasks starting at {schedule_start_dt.strftime('%I:%M %p')}...")

        for event in source_events:
            orig_start = datetime.datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
            orig_end = datetime.datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
            
            new_start = orig_start + time_shift
            new_end = orig_end + time_shift

            new_event = {
                'summary': event.get('summary', 'Busy'),
                'description': event.get('description', ''),
                'start': {'dateTime': new_start.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': new_end.isoformat(), 'timeZone': config.USER_TIMEZONE},
            }
            if 'colorId' in event: new_event['colorId'] = event['colorId']

            service.events().insert(calendarId='primary', body=new_event).execute()
            time.sleep(0.3)

        final_msg = (
            f"✅ **Schedule Deployed!**\n\n"
            f"*First task begins at {schedule_start_dt.strftime('%I:%M %p')}*\n\n"
            f"💡 *Tip: To customize your Early, Normal, and Late duration slots or enable 24h mode, tap ⚙️ Settings!*"
        )
        bot_instance.send_message(chat_id, final_msg, parse_mode="Markdown")

    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Google access expired/revoked. Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Error: {str(e)}")

def clear_day_events(chat_id: str, target_date: datetime.date, bot_instance):
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.min))
        end_dt = tz.localize(datetime.datetime.combine(target_date, datetime.time.max))
        
        events_result = service.events().list(
            calendarId='primary', timeMin=start_dt.isoformat(), timeMax=end_dt.isoformat(), singleEvents=True
        ).execute()
        events = events_result.get('items', [])
        
        for e in events:
            service.events().delete(calendarId='primary', eventId=e['id']).execute()
            time.sleep(0.2)
            
        bot_instance.send_message(chat_id, f"✅ Cleared {len(events)} events from {target_date.strftime('%b %d')}.")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to clear: {str(e)}")

def add_custom_task(chat_id: str, target_date: datetime.date, name: str, start_time: datetime.time, duration_hours: float, bot_instance):
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, start_time))
        end_dt = start_dt + datetime.timedelta(hours=duration_hours)
        
        new_event = {
            'summary': name,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'colorId': '11' # Tomato Red
        }
        service.events().insert(calendarId='primary', body=new_event).execute()
        bot_instance.send_message(chat_id, f"✅ Task *{name}* added to {target_date.strftime('%b %d')} at {start_time.strftime('%H:%M')}.", parse_mode="Markdown")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to add task: {str(e)}")