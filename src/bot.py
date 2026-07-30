import time
import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from src.database import get_user_token, get_user_profile, update_user_profile
from src.calendar_service import execute_schedule_creation, clear_day_events, add_custom_task, tz

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
user_states = {}

def is_authenticated(chat_id: str) -> bool:
    return get_user_token(chat_id) is not None

@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    chat_id = str(message.chat.id)
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(chat_id, f"👋 Welcome to Vector Workflows!\n\nPlease authorize your Google Calendar. Copy and open this link in Chrome:\n\n{auth_url}")
        return

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🌅 Awake Now", callback_data="awake_now"), InlineKeyboardButton("🗓️ Plan", callback_data="plan_menu"))
    markup.row(InlineKeyboardButton("➕ Add Task", callback_data="add_task_menu"), InlineKeyboardButton("🧹 Clear Day", callback_data="clear_menu"))
    markup.row(InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu"))
    
    bot.send_message(chat_id, "🤖 **Main Menu**\nChoose an action:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = str(call.message.chat.id)
    
    # ALWAYS answer the callback query to stop Telegram loading spinner!
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(chat_id, f"🔒 Please log in first:\n\n{auth_url}")
        return

    # --- MAIN FEATURES ---
    if call.data == "awake_now":
        now = datetime.datetime.now(tz).replace(tzinfo=None)
        bot.send_message(chat_id, f"Processing current time: {now.strftime('%I:%M %p')}...")
        execute_schedule_creation(chat_id, now, bot)

    # --- PLAN MENU ---
    elif call.data == "plan_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="plan_today"), InlineKeyboardButton("Tomorrow", callback_data="plan_tomorrow"), InlineKeyboardButton("Custom", callback_data="plan_custom"))
        bot.send_message(chat_id, "Which day are you planning for?", reply_markup=markup)

    elif call.data in ["plan_today", "plan_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "plan_today" else current_date + datetime.timedelta(days=1)
        user_states[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%A, %b %d')}**.\n\nWhat time do you plan to wake up?\n*(24-hour format, e.g. 04:15, 08:30)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_plan_time)

    elif call.data == "plan_custom":
        user_states[chat_id] = {'action': 'plan'}
        msg = bot.send_message(chat_id, "Reply with the date in `DD-MM-YYYY` format (e.g., 25-07-2026):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- CLEAR MENU ---
    elif call.data == "clear_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="clear_today"), InlineKeyboardButton("Tomorrow", callback_data="clear_tomorrow"), InlineKeyboardButton("Custom", callback_data="clear_custom"))
        bot.send_message(chat_id, "Which day do you want to clear?", reply_markup=markup)

    elif call.data in ["clear_today", "clear_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "clear_today" else current_date + datetime.timedelta(days=1)
        bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
        clear_day_events(chat_id, target_date, bot)

    elif call.data == "clear_custom":
        user_states[chat_id] = {'action': 'clear'}
        msg = bot.send_message(chat_id, "Reply with the date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- ADD TASK MENU ---
    elif call.data == "add_task_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="add_today"), InlineKeyboardButton("Tomorrow", callback_data="add_tomorrow"), InlineKeyboardButton("Custom", callback_data="add_custom"))
        bot.send_message(chat_id, "When is this task for?", reply_markup=markup)

    elif call.data in ["add_today", "add_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "add_today" else current_date + datetime.timedelta(days=1)
        user_states[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%A, %b %d')}**.\n\nWhat is the name of the task?", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_name)

    elif call.data == "add_custom":
        user_states[chat_id] = {'action': 'add'}
        msg = bot.send_message(chat_id, "Reply with the date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --- SETTINGS MENU ---
    elif call.data == "settings_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏰ Wake-Up Window", callback_data="set_window"), InlineKeyboardButton("🌐 24H Mode", callback_data="toggle_24h"))
        markup.row(InlineKeyboardButton("⏳ Custom Slot Durations", callback_data="set_durations"), InlineKeyboardButton("📅 Template Dates", callback_data="set_templates"))
        bot.send_message(chat_id, "⚙️ **Settings**\nSelect a configuration option:", reply_markup=markup, parse_mode="Markdown")

    elif call.data == "toggle_24h":
        profile = get_user_profile(chat_id)
        profile['mode_24h'] = not profile.get('mode_24h', False)
        update_user_profile(chat_id, profile)
        status = "ENABLED (Wake up anytime mode active)" if profile['mode_24h'] else "DISABLED (Standard wake windows active)"
        bot.send_message(chat_id, f"🌐 **24-Hour Mode** is now **{status}**.", parse_mode="Markdown")

    elif call.data == "set_window":
        msg = bot.send_message(chat_id, "What is the absolute **EARLIEST** time you usually wake up?\n*(Reply in HH:MM format, e.g. 04:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_earliest_window)

    elif call.data == "set_durations":
        msg = bot.send_message(chat_id, "Enter durations for Early, Normal, and Late slots in hours separated by commas.\n\n*(e.g. `2, 4, 1` means Early = 2h, Normal = 4h, Late = 1h)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_slot_durations)

    elif call.data == "set_templates":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Early", callback_data="edit_tpl_early"), InlineKeyboardButton("Normal", callback_data="edit_tpl_normal"), InlineKeyboardButton("Late", callback_data="edit_tpl_late"))
        bot.send_message(chat_id, "Which template date do you want to change?", reply_markup=markup)

    elif call.data.startswith("edit_tpl_"):
        slot = call.data.split("_")[2]
        user_states[chat_id] = {'editing_slot': slot}
        msg = bot.send_message(chat_id, f"Editing **{slot.upper()}** template.\nReply with date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_template_date)

# === STEP HANDLERS ===

def process_custom_date(message):
    chat_id = str(message.chat.id)
    try:
        target_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").date()
        action = user_states.get(chat_id, {}).get('action')
        
        if action == "plan":
            user_states[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%A, %b %d')}**.\n\nWhat time do you plan to wake up? (HH:MM):", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_plan_time)
        elif action == "clear":
            bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
            clear_day_events(chat_id, target_date, bot)
            if chat_id in user_states: del user_states[chat_id]
        elif action == "add":
            user_states[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%A, %b %d')}**.\n\nTask name?:", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_add_task_name)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format. Use DD-MM-YYYY.")

def process_plan_time(message):
    chat_id = str(message.chat.id)
    try:
        chosen_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        chosen_date = user_states[chat_id]['date']
        target_datetime = datetime.datetime.combine(chosen_date, chosen_time)
        
        bot.send_message(chat_id, f"Preparing schedule for {target_datetime.strftime('%b %d at %I:%M %p')}...")
        execute_schedule_creation(chat_id, target_datetime, bot)
        if chat_id in user_states: del user_states[chat_id]
    except Exception:
        bot.send_message(chat_id, "❌ Error parsing time. Use /menu to restart.")

def process_add_task_name(message):
    chat_id = str(message.chat.id)
    user_states[chat_id]['name'] = message.text
    msg = bot.send_message(chat_id, "Start time? *(HH:MM 24-hr format, e.g. 14:30)*", parse_mode="Markdown")
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

def process_earliest_window(message):
    chat_id = str(message.chat.id)
    try:
        earliest_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")
        user_states[chat_id] = {'earliest': earliest_time}
        msg = bot.send_message(chat_id, "What is the absolute **LATEST** time you wake up? *(e.g. 12:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_latest_window)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format.")

def process_latest_window(message):
    chat_id = str(message.chat.id)
    try:
        latest_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").strftime("%H:%M")
        earliest_time = user_states[chat_id]['earliest']
        
        profile = get_user_profile(chat_id)
        profile['wake_window']['earliest'] = earliest_time
        profile['wake_window']['latest'] = latest_time
        update_user_profile(chat_id, profile)
        
        bot.send_message(chat_id, f"✅ Saved wake window: **{earliest_time} to {latest_time}**.", parse_mode="Markdown")
        del user_states[chat_id]
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format.")

def process_slot_durations(message):
    chat_id = str(message.chat.id)
    try:
        parts = [float(x.strip()) for x in message.text.split(",")]
        if len(parts) != 3: raise ValueError()
        
        profile = get_user_profile(chat_id)
        profile['slot_durations'] = {"early": parts[0], "normal": parts[1], "late": parts[2]}
        update_user_profile(chat_id, profile)
        
        bot.send_message(chat_id, f"✅ Custom slot durations set:\n• Early: {parts[0]}h\n• Normal: {parts[1]}h\n• Late: {parts[2]}h", parse_mode="Markdown")
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format. Enter 3 numbers separated by commas (e.g. `2, 4, 1`).")

def process_template_date(message):
    chat_id = str(message.chat.id)
    try:
        new_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").strftime("%d-%m-%Y")
        slot = user_states[chat_id]['editing_slot']
        
        profile = get_user_profile(chat_id)
        profile['template_dates'][slot] = new_date
        update_user_profile(chat_id, profile)
        
        bot.send_message(chat_id, f"✅ **{slot.capitalize()}** template source date set to {new_date}.", parse_mode="Markdown")
        del user_states[chat_id]
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format. Use DD-MM-YYYY.")

def start_bot():
    print("🚀 Vector Workflows UI started. Listening for buttons 24/7...")
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"⚠️ Telegram Error: {e}")
            time.sleep(5)