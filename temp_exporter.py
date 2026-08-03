import datetime
import json
import pytz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import config
from pymongo import MongoClient

TZ = pytz.timezone(config.USER_TIMEZONE)


def export_templates():
    client = MongoClient(config.MONGO_URI)
    db = client['vector_workflows']
    users_collection = db['google_tokens']

    user_doc = users_collection.find_one({"token": {"$exists": True}})

    if not user_doc:
        print("❌ No Google tokens found in database. Have you logged in yet?")
        return

    token_dict = user_doc['token']
    print("✅ Found token in database! Connecting to Google Calendar...\n")

    creds = Credentials(**token_dict)
    service = build('calendar', 'v3', credentials=creds)

    # Fetch a padded window (one extra day either side) so no event near the
    # boundary gets clipped by timeMax precision. Actual date bucketing below
    # is done per-event in local time, so the padding can't cause miscounts.
    start_dt = TZ.localize(datetime.datetime(2026, 5, 30, 0, 0))
    end_dt = TZ.localize(datetime.datetime(2026, 6, 4, 0, 0))

    print("--- Fetching events for 31 May - 2 Jun 2026 (padded window) ---")

    events = []
    page_token = None

    while True:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            showDeleted=False,
            maxResults=2500,
            pageToken=page_token
        ).execute()

        events.extend(events_result.get('items', []))
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

    # Correct mapping, matching what was actually asked for:
    # 31 May -> normal, 1 Jun -> early, 2 Jun -> late
    exported_data = {"normal": [], "early": [], "late": []}
    date_mapping = {
        "31-05-2026": "normal",
        "01-06-2026": "early",
        "02-06-2026": "late",
    }

    skipped_all_day = 0

    for e in events:
        task_name = e.get('summary', 'Busy')
        start_time_str = e['start'].get('dateTime')  # None for all-day events
        end_time_str = e['end'].get('dateTime')

        if not start_time_str:
            # All-day event (only a 'date' key present) — skip entirely per spec
            skipped_all_day += 1
            continue

        dt = datetime.datetime.fromisoformat(start_time_str)
        if dt.tzinfo:
            dt = dt.astimezone(TZ)
        else:
            dt = TZ.localize(dt)
        day_str = dt.strftime("%d-%m-%Y")

        if day_str in date_mapping:
            slot = date_mapping[day_str]
            exported_data[slot].append({
                "summary": task_name,
                "description": e.get('description', ''),
                "start_time": start_time_str,
                "end_time": end_time_str,
                "colorId": e.get('colorId', '5')
            })
            print(f"  • Caught in {slot.upper()} ({day_str}): {task_name}")

    print("\n--- Summary ---")
    for slot in ["normal", "early", "late"]:
        print(f"✅ Total found for {slot}: {len(exported_data[slot])}")
    if skipped_all_day:
        print(f"↷ Skipped {skipped_all_day} all-day event(s)")

    with open("templates.json", "w") as f:
        json.dump(exported_data, f, indent=4)

    print("\n🎉 Export complete! Written to 'templates.json'.")


if __name__ == "__main__":
    export_templates()