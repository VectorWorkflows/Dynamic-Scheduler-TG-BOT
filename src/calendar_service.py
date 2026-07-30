import datetime
import time
import pytz
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import config
from src.database import get_user_token, get_user_profile, update_user_profile, delete_user_token

SCOPES = ["https://www.googleapis.com/auth/calendar"]
tz = pytz.timezone(config.USER_TIMEZONE)

class AuthError(Exception): pass

def get_calendar_service(chat_id: str):
    token_dict = get_user_token(chat_id)
    if not token_dict: raise AuthError("Not Authenticated")
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

def get_next_quarter_hour(dt: datetime.datetime):
    minutes_to_add = 15 - (dt.minute % 15)
    return dt + datetime.timedelta(minutes=minutes_to_add)

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

def initialize_new_user(chat_id: str, service, bot_instance):
    profile = get_user_profile(chat_id)
    today = datetime.datetime.now(tz).date()
    early_date = today - datetime.timedelta(days=60)
    normal_date = today - datetime.timedelta(days=59)
    late_date = today - datetime.timedelta(days=58)
    
    profile['template_dates'] = {
        "early": early_date.strftime("%d-%m-%Y"),
        "normal": normal_date.strftime("%d-%m-%Y"),
        "late": late_date.strftime("%d-%m-%Y")
    }

    bot_instance.send_message(
        chat_id, 
        f"🛠️ **Initializing Calendar Templates...**\nCreating 11-block routines on past dates:\n\n"
        f"• Early Template: `{profile['template_dates']['early']}`\n"
        f"• Normal Template: `{profile['template_dates']['normal']}`\n"
        f"• Late Template: `{profile['template_dates']['late']}`",
        parse_mode="Markdown"
    )

    for key, date_str in profile['template_dates'].items():
        base_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
        base_dt = tz.localize(datetime.datetime.combine(base_date, datetime.time(5, 0)))
        
        for block in DEFAULT_ROUTINE_BLOCKS:
            start_dt = base_dt + datetime.timedelta(minutes=block['offset_min'])
            end_dt = start_dt + datetime.timedelta(minutes=block['duration'])
            
            summary = block['title']
            if key == "late" and "Walk" in summary: summary = "⏰ " + summary + " (Late Mode)"

            event = {
                'summary': summary, 'description': block['desc'],
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
                'colorId': block['colorId']
            }
            service.events().insert(calendarId='primary', body=event).execute()
            time.sleep(0.2)
            
    profile['is_initialized'] = True
    update_user_profile(chat_id, profile)
    bot_instance.send_message(chat_id, "✅ **Templates Injected!** You can customize those dates directly in Google Calendar anytime.")

def determine_dynamic_template(target_time: datetime.time, profile: dict):
    windows = profile.get('wake_windows', {})
    t_early = datetime.datetime.strptime(windows.get('earliest_start', '04:00'), "%H:%M").time()
    t_normal = datetime.datetime.strptime(windows.get('normal_start', '07:00'), "%H:%M").time()
    t_late = datetime.datetime.strptime(windows.get('late_start', '10:00'), "%H:%M").time()
    t_end = datetime.datetime.strptime(windows.get('latest_end', '13:00'), "%H:%M").time()

    if profile.get('mode_24h', False):
        if t_early <= target_time < t_normal: return "early", profile['template_dates']['early']
        elif t_normal <= target_time < t_late: return "normal", profile['template_dates']['normal']
        else: return "late", profile['template_dates']['late']

    if t_early <= target_time < t_normal:
        return "early", profile['template_dates']['early']
    elif t_normal <= target_time < t_late:
        return "normal", profile['template_dates']['normal']
    elif t_late <= target_time <= t_end:
        return "late", profile['template_dates']['late']
    
    return None, None

def execute_schedule_creation(chat_id: str, target_datetime: datetime.datetime, bot_instance):
    try:
        service = get_calendar_service(chat_id)
        profile = get_user_profile(chat_id)
        
        if not profile.get('is_initialized', False) or not profile.get('template_dates'):
            initialize_new_user(chat_id, service, bot_instance)
            profile = get_user_profile(chat_id)

        template_key, template_date_str = determine_dynamic_template(target_datetime.time(), profile)
        
        if not template_key:
            bot_instance.send_message(
                chat_id, 
                f"❌ Wake time `{target_datetime.strftime('%H:%M')}` is outside your allowed window ({profile['wake_windows']['earliest_start']} - {profile['wake_windows']['latest_end']}).\n\n"
                f"Enable 24H Mode or update your Wake Windows in ⚙️ Settings / Configure!",
                parse_mode="Markdown"
            )
            return

        schedule_start_dt = get_next_quarter_hour(target_datetime)
        source_date = datetime.datetime.strptime(template_date_str, "%d-%m-%Y").date()
        source_start_dt = tz.localize(datetime.datetime.combine(source_date, datetime.time.min))
        source_end_dt = source_start_dt + datetime.timedelta(hours=23, minutes=59)

        bot_instance.send_message(chat_id, f"🔍 Slot matched: *{template_key.upper()}*\nFetching template from `{template_date_str}`...", parse_mode="Markdown")

        events_result = service.events().list(
            calendarId='primary', timeMin=source_start_dt.isoformat(), timeMax=source_end_dt.isoformat(), singleEvents=True, orderBy='startTime'
        ).execute()
        source_events = events_result.get('items', [])

        if not source_events:
            bot_instance.send_message(chat_id, f"⚠️ No events found on source date `{template_date_str}`! Add events to that date in Google Calendar.", parse_mode="Markdown")
            return

        first_event_start = datetime.datetime.fromisoformat(source_events[0]['start'].get('dateTime', source_events[0]['start'].get('date')))
        time_shift = tz.localize(schedule_start_dt) - first_event_start

        bot_instance.send_message(chat_id, f"📝 Copying {len(source_events)} tasks starting at {schedule_start_dt.strftime('%I:%M %p')}...")

        for event in source_events:
            orig_start = datetime.datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
            orig_end = datetime.datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
            
            new_event = {
                'summary': event.get('summary', 'Busy'),
                'description': event.get('description', ''),
                'start': {'dateTime': (orig_start + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
                'end': {'dateTime': (orig_end + time_shift).isoformat(), 'timeZone': config.USER_TIMEZONE},
            }
            if 'colorId' in event: new_event['colorId'] = event['colorId']
            service.events().insert(calendarId='primary', body=new_event).execute()
            time.sleep(0.2)

        bot_instance.send_message(chat_id, f"✅ **Schedule Deployed!**\nFirst task begins at {schedule_start_dt.strftime('%I:%M %p')}.", parse_mode="Markdown")

    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Google access expired or revoked. Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Error: {str(e)}")

def clear_day_events(chat_id: str, target_date: datetime.date, bot_instance):
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

def add_custom_task(chat_id: str, target_date: datetime.date, name: str, start_time: datetime.time, duration_hours: float, bot_instance):
    try:
        service = get_calendar_service(chat_id)
        start_dt = tz.localize(datetime.datetime.combine(target_date, start_time))
        end_dt = start_dt + datetime.timedelta(hours=duration_hours)
        event = {
            'summary': name,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': config.USER_TIMEZONE},
            'colorId': '11'
        }
        service.events().insert(calendarId='primary', body=event).execute()
        bot_instance.send_message(chat_id, f"✅ Task *{name}* added to {target_date.strftime('%b %d')} at {start_time.strftime('%H:%M')}.", parse_mode="Markdown")
    except AuthError:
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot_instance.send_message(chat_id, f"🔒 Please log in again:\n\n{auth_url}")
    except Exception as e:
        bot_instance.send_message(chat_id, f"❌ Failed to add task: {str(e)}")