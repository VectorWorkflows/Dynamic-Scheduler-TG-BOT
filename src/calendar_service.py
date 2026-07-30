import datetime
import time
import pytz
from typing import Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import config
from src.database import get_user_token

SCOPES = ["https://www.googleapis.com/auth/calendar"]
tz = pytz.timezone(config.USER_TIMEZONE)

# Your Custom Schedule Templates
TEMPLATES = {
    "early": {
        "start_limit": datetime.time(4, 0),
        "end_limit": datetime.time(6, 30),
        "copy_from_date": datetime.date(2026, 7, 9),
        "copy_from_time": datetime.time(4, 0),
        "custom_message": "🌅 You are up EARLY! Do a light workout, bath, get ready and eat before taking the dog out on the walk."
    },
    "normal": {
        "start_limit": datetime.time(6, 31),
        "end_limit": datetime.time(9, 30),
        "copy_from_date": datetime.date(2026, 7, 5),
        "copy_from_time": datetime.time(8, 0),
        "custom_message": "☀️ Good morning! Let's get the standard routine started. Hydrate and get to it."
    },
    "late": {
        "start_limit": datetime.time(9, 31),
        "end_limit": datetime.time(12, 0),
        "copy_from_date": datetime.date(2026, 6, 30),
        "copy_from_time": datetime.time(12, 0),
        "custom_message": "⏰ Don't Walk Odin Today. Try to get tasks done little bit quicker."
    }
}

def get_calendar_service(chat_id: str):
    """Builds the Google Calendar service using the user's saved token from DB."""
    token_dict = get_user_token(chat_id)
    if not token_dict:
        raise Exception("Not Authenticated")
    
    creds = Credentials(
        token=token_dict.get('token'),
        refresh_token=token_dict.get('refresh_token'),
        token_uri=token_dict.get('token_uri'),
        client_id=token_dict.get('client_id'),
        client_secret=token_dict.get('client_secret'),
        scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=creds)

def get_next_quarter_hour(dt: datetime.datetime):
    minutes_to_add = 15 - (dt.minute % 15)
    return dt + datetime.timedelta(minutes=minutes_to_add)

def determine_template(target_time: datetime.time):
    for key, data in TEMPLATES.items():
        if data["start_limit"] <= target_time <= data["end_limit"]:
            return key, data
    return None, None

def execute_schedule_creation(chat_id: str, target_datetime: datetime.datetime, bot_instance):
    """Fetches templates and builds the schedule."""
    try:
        service = get_calendar_service(chat_id)
        template_key, template_data = determine_template(target_datetime.time())
        
        if not template_key:
            bot_instance.send_message(chat_id, "❌ Time is out of bounds. Must be between 4:00 AM and 12:00 Noon.")
            return

        schedule_start_dt = get_next_quarter_hour(target_datetime)
        source_start_dt = tz.localize(datetime.datetime.combine(template_data["copy_from_date"], template_data["copy_from_time"]))
        source_end_dt = source_start_dt + datetime.timedelta(hours=16)

        bot_instance.send_message(chat_id, f"🔍 Found slot: *{template_key.upper()}*\nFetching template from {template_data['copy_from_date']}...", parse_mode="Markdown")

        events_result = service.events().list(
            calendarId='primary', timeMin=source_start_dt.isoformat(), 
            timeMax=source_end_dt.isoformat(), singleEvents=True, orderBy='startTime'
        ).execute()
        source_events = events_result.get('items', [])

        if not source_events:
            bot_instance.send_message(chat_id, "⚠️ No events found on the source date to copy!")
            return

        localized_target_start = tz.localize(schedule_start_dt)
        time_shift = localized_target_start - source_start_dt

        bot_instance.send_message(chat_id, f"📝 Copying {len(source_events)} tasks...")

        for event in source_events:
            orig_start = datetime.datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
            orig_end = datetime.datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
            
            new_start = orig_start + time_shift
            new_end = orig_end + time_shift

            summary = event.get('summary', 'Busy')
            
            # Weekend swapping logic
            if target_datetime.date().weekday() in [5, 6]:
                if "reading" in summary.lower(): summary = "Typing Practice"
                elif "workout" in summary.lower(): summary = "Unexpected Work"

            new_event = {
                'summary': summary,
                'description': event.get('description', ''),
                'start': {'dateTime': new_start.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': new_end.isoformat(), 'timeZone': config.USER_TIMEZONE},
            }
            if 'colorId' in event: 
                new_event['colorId'] = event['colorId']

            service.events().insert(calendarId='primary', body=new_event).execute()
            time.sleep(0.5)

        final_msg = f"✅ **Schedule Deployed!**\n\n{template_data['custom_message']}\n\n*First task begins at {localized_target_start.strftime('%I:%M %p')}*"
        bot_instance.send_message(chat_id, final_msg, parse_mode="Markdown")

    except Exception as e:
        if "Not Authenticated" in str(e) or "invalid_grant" in str(e):
            bot_instance.send_message(chat_id, f"🔒 Session expired. Please login again:\n{config.BASE_URL}/login?chat_id={chat_id}")
        else:
            bot_instance.send_message(chat_id, f"❌ Error: {str(e)}")

def clear_day_events(chat_id: str, target_date: datetime.date, bot_instance):
    """Deletes all events on a specific day."""
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
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to clear: {str(e)}")

def add_custom_task(chat_id: str, target_date: datetime.date, name: str, start_time: datetime.time, duration_hours: float, bot_instance):
    """Adds a red custom task to the calendar."""
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, start_time))
        end_dt = start_dt + datetime.timedelta(hours=duration_hours)
        
        new_event = {
            'summary': name,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'colorId': '11'  # 'Tomato' red in Google Calendar
        }
        service.events().insert(calendarId='primary', body=new_event).execute()
        bot_instance.send_message(chat_id, f"✅ Task *{name}* added to {target_date.strftime('%b %d')} at {start_time.strftime('%H:%M')}.", parse_mode="Markdown")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to add task: {str(e)}")