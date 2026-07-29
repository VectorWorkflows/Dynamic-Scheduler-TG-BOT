import datetime
from typing import List, Dict, Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import config

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_calendar_service():
    """Authenticates using stored token or initiates local OAuth server."""
    creds = None
    if config.TOKEN_FILE_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE_PATH), SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_FILE_PATH.exists():
                raise FileNotFoundError(
                    f"Missing credentials file at '{config.CREDENTIALS_FILE_PATH}'. "
                    "Make sure your credentials.json file is inside the main 'dynamic-scheduler' root folder."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(config.TOKEN_FILE_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def create_calendar_event(service: Any, summary: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> Dict[str, Any]:
    """Inserts an event into the user's primary Google Calendar."""
    event = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": config.USER_TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": config.USER_TIMEZONE},
    }
    return service.events().insert(calendarId="primary", body=event).execute()


def generate_circadian_schedule(awake_time_str: str) -> List[Dict[str, str]]:
    """
    Calculates dynamic time blocks based on wake time and posts them to Google Calendar.
    Expected format: "HH:MM" (e.g., "07:30")
    """
    service = get_calendar_service()
    today = datetime.date.today()
    hours, minutes = map(int, awake_time_str.split(":"))
    wake_time = datetime.datetime(today.year, today.month, today.day, hours, minutes)
    
    buffer = datetime.timedelta(minutes=config.DEFAULT_BUFFER_MINUTES)
    
    morning_start = wake_time
    morning_end = morning_start + datetime.timedelta(minutes=45)
    deep1_start = morning_end + buffer
    deep1_end = deep1_start + datetime.timedelta(minutes=90)
    deep2_start = deep1_end + buffer
    deep2_end = deep2_start + datetime.timedelta(minutes=90)
    
    schedule_blocks = [
        ("☀️ Morning Light & Cortisol Peak", morning_start, morning_end),
        ("🧠 Deep Work Block #1", deep1_start, deep1_end),
        ("⚡ Deep Work Block #2", deep2_start, deep2_end),
    ]
    
    created_events = []
    for title, start_dt, end_dt in schedule_blocks:
        event = create_calendar_event(service, title, start_dt, end_dt)
        created_events.append({
            "title": title,
            "start": start_dt.strftime("%H:%M"),
            "end": end_dt.strftime("%H:%M"),
            "link": event.get("htmlLink", "")
        })
        
    return created_events