import time
import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from src.database import get_user_token, get_user_profile, update_user_profile, reset_user_profile, delete_user_data
from src.calendar_service import execute_schedule_creation, clear_day_events, add_custom_task, tz

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
user_states = {}

def is_authenticated(chat_id: str) -> bool: 
    return get_user_token(chat_id) is not None

@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    chat_id = str(message.chat.id)
    
    # STRICT AUTH GATE: Unauthenticated users get ONLY the login link, no menus/buttons
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"👋 Welcome to Vector Workflows!\n\nPlease authorize your Google Calendar before accessing the bot:\n\n👉 {auth_url}"
        )
        return

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🌅 Awake Now", callback_data="awake_now"), InlineKeyboardButton("🗓️ Plan", callback_data="plan_menu"))
    markup.row(InlineKeyboardButton("➕ Add Task", callback_data="add_task_menu"), InlineKeyboardButton("🧹 Clear Day", callback_data="clear_menu"))
    markup.row(InlineKeyboardButton("⚙️ Settings / Configure", callback_data="settings_menu"))
    bot.send_message(chat_id, "🤖 **Main Menu**\nChoose an action:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = str(call.message.chat.id)
    try: bot.answer_callback_query(call.id)
    except Exception: pass

    # STRICT AUTH GATE FOR ALL BUTTON CLICKS
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"🔒 Your session has expired or you are not logged in. Please authorize first:\n\n👉 {auth_url}"
        )
        return

    # --- MAIN ACTIONS ---
    if call.data == "awake_now":
        now = datetime.datetime.now(tz).replace(tzinfo=None)
        execute_schedule_creation(chat_id, now, bot)

    # --- PLAN MENU ---
    elif call.data == "plan_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="plan_today"), InlineKeyboardButton("Tomorrow", callback_data="plan_tomorrow"), InlineKeyboardButton("Custom Date", callback_data="plan_custom"))
        bot.send_message(chat_id, "Which day are you planning for?", reply_markup=markup)

    elif call.data in ["plan_today", "plan_tomorrow"]:
        target_date = datetime.datetime.now(tz).date() if call.data == "plan_today" else datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
        user_states[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%b %d')}**.\nWhat time will you wake up? *(HH:MM 24-hr, e.g. 06:30)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_plan_time)

    elif call.data == "plan_custom":
        user_states[chat_id] = {'action': 'plan'}
        msg = bot.send_message(chat_id, "Reply with date in `DD-MM-YYYY` format (e.g. 25-07-2026):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- CLEAR MENU ---
    elif call.data == "clear_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="clear_today"), InlineKeyboardButton("Tomorrow", callback_data="clear_tomorrow"), InlineKeyboardButton("Custom Date", callback_data="clear_custom"))
        bot.send_message(chat_id, "Which day do you want to clear?", reply_markup=markup)

    elif call.data in ["clear_today", "clear_tomorrow"]:
        target_date = datetime.datetime.now(tz).date() if call.data == "clear_today" else datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
        bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
        clear_day_events(chat_id, target_date, bot)

    elif call.data == "clear_custom":
        user_states[chat_id] = {'action': 'clear'}
        msg = bot.send_message(chat_id, "Reply with date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- ADD TASK MENU ---
    elif call.data == "add_task_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="add_today"), InlineKeyboardButton("Tomorrow", callback_data="add_tomorrow"), InlineKeyboardButton("Custom Date", callback_data="add_custom"))
        bot.send_message(chat_id, "When is this task for?", reply_markup=markup)

    elif call.data in ["add_today", "add_tomorrow"]:
        target_date = datetime.datetime.now(tz).date() if call.data == "add_today" else datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
        user_states[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%b %d')}**.\nWhat is the task name?", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_name)

    elif call.data == "add_custom":
        user_states[chat_id] = {'action': 'add'}
        msg = bot.send_message(chat_id, "Reply with date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- SETTINGS MENU ---
    elif call.data == "settings_menu":
        profile = get_user_profile(chat_id)
        mode_str = "ON (24-Hour Active)" if profile.get('mode_24h') else "OFF (Standard Windows Active)"
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏰ Configure Wake Windows", callback_data="set_windows"))
        markup.row(InlineKeyboardButton(f"🌐 24H Mode: {mode_str}", callback_data="toggle_24h"))
        markup.row(InlineKeyboardButton("📅 Custom Template Dates", callback_data="set_templates"))
        markup.row(InlineKeyboardButton("🗑️ Reset Settings & Logout", callback_data="reset_menu"))
        
        bot.send_message(chat_id, "⚙️ **Settings / Configure**\nCustomize your preferences below:", reply_markup=markup, parse_mode="Markdown")

    elif call.data == "toggle_24h":
        profile = get_user_profile(chat_id)
        profile['mode_24h'] = not profile.get('mode_24h', False)
        update_user_profile(chat_id, profile)
        bot.send_message(chat_id, f"🌐 **24-Hour Mode** is now **{'ENABLED' if profile['mode_24h'] else 'DISABLED'}**.")

    elif call.data == "set_windows":
        msg = bot.send_message(chat_id, "1️⃣ What time does your **EARLIEST** wake window start?\n*(HH:MM format, e.g. 04:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_window_early)

    elif call.data == "set_templates":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Early", callback_data="edit_tpl_early"), InlineKeyboardButton("Normal", callback_data="edit_tpl_normal"), InlineKeyboardButton("Late", callback_data="edit_tpl_late"))
        bot.send_message(chat_id, "Which template date do you want to change?", reply_markup=markup)

    elif call.data.startswith("edit_tpl_"):
        slot = call.data.split("_")[2]
        user_states[chat_id] = {'editing_slot': slot}
        msg = bot.send_message(chat_id, f"Editing **{slot.upper()}** template.\nReply with date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_template_date)

    elif call.data == "reset_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Reset Windows Only", callback_data="reset_win"))
        markup.row(InlineKeyboardButton("Factory Reset Profile & Templates", callback_data="reset_full"))
        markup.row(InlineKeyboardButton("🔴 Delete Account Data & Logout", callback_data="delete_account"))
        bot.send_message(chat_id, "🗑️ **Reset / Logout Menu**\nSelect an option:", reply_markup=markup)

    elif call.data == "reset_win":
        reset_user_profile(chat_id, "windows")
        bot.send_message(chat_id, "✅ Wake windows reset to default (04:00 AM – 01:00 PM).")

    elif call.data == "reset_full":
        reset_user_profile(chat_id, "full")
        bot.send_message(chat_id, "🧹 Full profile wiped. Tap **Awake Now** to re-inject fresh 11-block templates into Google Calendar!")

    elif call.data == "delete_account":
        delete_user_data(chat_id)
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"🔴 **Account Data Deleted & Logged Out.**\nYour stored Google OAuth token and profile have been completely wiped from MongoDB.\n\nTo use the bot again, authorize here:\n\n👉 {auth_url}",
            parse_mode="Markdown"
        )

# === STEP HANDLERS ===
def process_custom_date(message):
    chat_id = str(message.chat.id)
    try:
        target_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").date()
        action = user_states.get(chat_id, {}).get('action')
        
        if action == "plan":
            user_states[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%b %d')}**.\nWake time? (HH:MM):", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_plan_time)
        elif action == "clear":
            bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
            clear_day_events(chat_id, target_date, bot)
            if chat_id in user_states: del user_states[chat_id]
        elif action == "add":
            user_states[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%b %d')}**.\nTask name?:", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_add_task_name)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid date format. Use DD-MM-YYYY.")

def process_plan_time(message):
    chat_id = str(message.chat.id)
    try:
        target_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        target_datetime = datetime.datetime.combine(user_states[chat_id]['date'], target_time)
        bot.send_message(chat_id, f"Preparing schedule for {target_datetime.strftime('%b %d at %I:%M %p')}...")
        execute_schedule_creation(chat_id, target_datetime, bot)
        if chat_id in user_states: del user_states[chat_id]
    except Exception: bot.send_message(chat_id, "❌ Invalid time format. Use HH:MM.")

def process_add_task_name(message):
    chat_id = str(message.chat.id)
    user_states[chat_id]['name'] = message.text
    msg = bot.send_message(chat_id, "Start time? *(HH:MM 24-hr, e.g. 14:30)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_task_time)

def process_add_task_time(message):
    chat_id = str(message.chat.id)
    try:
        chosen_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        user_states[chat_id]['start_time'] = chosen_time
        msg = bot.send_message(chat_id, "Duration in hours? *(e.g. 1, 1.5, 2)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_duration)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid time format.")

def process_add_task_duration(message):
    chat_id = str(message.chat.id)
    try:
        duration_hours = float(message.text.strip())
        data = user_states[chat_id]
        add_custom_task(chat_id, data['date'], data['name'], data['start_time'], duration_hours, bot)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid duration.")
    finally:
        if chat_id in user_states: del user_states[chat_id]

def process_window_early(message):
    chat_id = str(message.chat.id)
    try:
        user_states[chat_id] = {'earliest_start': datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")}
        msg = bot.send_message(chat_id, "2️⃣ What time does your **NORMAL** window start?\n*(HH:MM, e.g. 07:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_window_normal)
    except Exception: bot.send_message(chat_id, "❌ Invalid time format.")

def process_window_normal(message):
    chat_id = str(message.chat.id)
    try:
        user_states[chat_id]['normal_start'] = datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")
        msg = bot.send_message(chat_id, "3️⃣ What time does your **LATE** window start?\n*(HH:MM, e.g. 10:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_window_late)
    except Exception: bot.send_message(chat_id, "❌ Invalid time format.")

def process_window_late(message):
    chat_id = str(message.chat.id)
    try:
        user_states[chat_id]['late_start'] = datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")
        msg = bot.send_message(chat_id, "4️⃣ What is the absolute **LATEST** time you wake up?\n*(HH:MM, e.g. 13:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_window_end)
    except Exception: bot.send_message(chat_id, "❌ Invalid time format.")

def process_window_end(message):
    chat_id = str(message.chat.id)
    try:
        latest = datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")
        profile = get_user_profile(chat_id)
        profile['wake_windows'] = {
            "earliest_start": user_states[chat_id]['earliest_start'],
            "normal_start": user_states[chat_id]['normal_start'],
            "late_start": user_states[chat_id]['late_start'],
            "latest_end": latest
        }
        update_user_profile(chat_id, profile)
        bot.send_message(
            chat_id, 
            f"✅ **Wake Windows Configured!**\n\n"
            f"• Early: `{profile['wake_windows']['earliest_start']}` - `{profile['wake_windows']['normal_start']}`\n"
            f"• Normal: `{profile['wake_windows']['normal_start']}` - `{profile['wake_windows']['late_start']}`\n"
            f"• Late: `{profile['wake_windows']['late_start']}` - `{profile['wake_windows']['latest_end']}`",
            parse_mode="Markdown"
        )
    except Exception: bot.send_message(chat_id, "❌ Invalid time format.")

def process_template_date(message):
    chat_id = str(message.chat.id)
    try:
        new_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").strftime("%d-%m-%Y")
        slot = user_states[chat_id]['editing_slot']
        
        profile = get_user_profile(chat_id)
        profile['template_dates'][slot] = new_date
        update_user_profile(chat_id, profile)
        
        bot.send_message(chat_id, f"✅ **{slot.capitalize()}** template source date set to `{new_date}`.", parse_mode="Markdown")
        del user_states[chat_id]
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid date format. Use DD-MM-YYYY.")

def start_bot():
    print("🚀 Vector Workflows UI started.")
    while True:
        try: bot.polling(none_stop=True)
        except Exception as e: time.sleep(5)