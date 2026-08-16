# ==========================================
# IMPORTS: Bringing in the necessary tools
# ==========================================
import time
import datetime
import telebot # The main Telegram bot library
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton # Used to build the clickable buttons
import config # Brings in your .env variables (Tokens, URLs)
from src.database import get_user_token, get_user_profile, update_user_profile, reset_user_profile, delete_user_data
from src.calendar_service import execute_schedule_creation, clear_day_events, add_custom_task, fetch_and_save_custom_template, tz

# Initialize the bot using the token from your .env file
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

# A temporary memory dictionary to hold user data between conversation steps (like dates, names, etc.)
user_states = {}

# ==========================================
# AUTHENTICATION CHECKER
# ==========================================
def is_authenticated(chat_id: str) -> bool: 
    """Checks if the user has a Google token saved in MongoDB."""
    return get_user_token(chat_id) is not None

# ==========================================
# DIAGNOSTIC PING (NO DATABASE)
# ==========================================
@bot.message_handler(commands=['ping'])
def ping_test(message):
    print("🏓 PING RECEIVED! (Bypassing Database)")
    bot.reply_to(message, "🏓 PONG! The bot is receiving messages perfectly!")



# ==========================================
# MAIN MENU HANDLER (/start or /menu)
# ==========================================
@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    """Fired whenever a user types /start or /menu."""
    chat_id = str(message.chat.id)
    
    # STRICT AUTH GATE: If they aren't logged in, stop here and ONLY show the login link.
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"👋 Welcome to Vector Workflows!\n\nPlease authorize your Google Calendar before accessing the bot:\n\n👉 {auth_url}"
        )
        return

    # If they are logged in, build the Main Menu buttons
    markup = InlineKeyboardMarkup()
    # row() puts buttons side-by-side. You can add as many as fit on the screen.
    markup.row(InlineKeyboardButton("🌅 Awake Now", callback_data="awake_now"), InlineKeyboardButton("🗓️ Plan", callback_data="plan_menu"))
    markup.row(InlineKeyboardButton("➕ Add Task", callback_data="add_task_menu"), InlineKeyboardButton("🧹 Clear Day", callback_data="clear_menu"))
    markup.row(InlineKeyboardButton("⚙️ Settings / Configure", callback_data="settings_menu"))
    
    # Send the menu to the user
    bot.send_message(chat_id, "🤖 **Main Menu**\nChoose an action:", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# BUTTON CLICK HANDLER (Catches EVERY button tap)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """Fired whenever ANY inline button is clicked."""
    chat_id = str(call.message.chat.id)
    
    # This stops the little loading clock animation on the Telegram button
    try: bot.answer_callback_query(call.id)
    except Exception: pass

    # STRICT AUTH GATE FOR BUTTONS: If their token was deleted, stop them from using buttons.
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"🔒 Your session has expired or you are not logged in. Please authorize first:\n\n👉 {auth_url}"
        )
        return

    # --------------------------------------------------
    # 1. AWAKE NOW BUTTON
    # --------------------------------------------------
    if call.data == "awake_now":
        profile = get_user_profile(chat_id)
        
        # --- NEW CHANGE: Check if 24-Hour Mode is active ---
        if profile.get('mode_24h', False):
            # If 24H mode is ON, ask them which routine they want to run
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("🌅 Early", callback_data="manual_awake_early"))
            markup.row(InlineKeyboardButton("☀️ Normal", callback_data="manual_awake_normal"))
            markup.row(InlineKeyboardButton("🌙 Late", callback_data="manual_awake_late"))
            bot.send_message(chat_id, "🌐 **24-Hour Mode Active**\nSince you wake up at any time, which routine do you want to run right now?", reply_markup=markup, parse_mode="Markdown")
        else:
            # If 24H mode is OFF, just run it automatically using the current time
            now = datetime.datetime.now(tz).replace(tzinfo=None)
            bot.send_message(chat_id, f"Processing current time: {now.strftime('%I:%M %p')}...")
            execute_schedule_creation(chat_id, now, bot)

    # --------------------------------------------------
    # 1.5. MANUAL AWAKE SELECTION (For 24-Hour Mode)
    # --------------------------------------------------
    elif call.data.startswith("manual_awake_"):
        # This extracts the word 'early', 'normal', or 'late' from the button's callback_data
        selected_slot = call.data.split("_")[2] 
        now = datetime.datetime.now(tz).replace(tzinfo=None)
        
        # We save their manual choice temporarily to the database.
        # (We will update calendar_service.py next to read this override and paste the right schedule!)
        profile = get_user_profile(chat_id)
        profile['temp_manual_override'] = selected_slot
        update_user_profile(chat_id, profile)
        
        bot.send_message(chat_id, f"Processing manual **{selected_slot.upper()}** routine for {now.strftime('%I:%M %p')}...", parse_mode="Markdown")
        execute_schedule_creation(chat_id, now, bot)

    # --------------------------------------------------
    # 2. PLAN MENU
    # --------------------------------------------------
    elif call.data == "plan_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="plan_today"), InlineKeyboardButton("Tomorrow", callback_data="plan_tomorrow"), InlineKeyboardButton("Custom Date", callback_data="plan_custom"))
        bot.send_message(chat_id, "Which day are you planning for?", reply_markup=markup)

    elif call.data in ["plan_today", "plan_tomorrow"]:
        # Figure out if they meant today or tomorrow based on timezone
        target_date = datetime.datetime.now(tz).date() if call.data == "plan_today" else datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
        
        # Save the date into temporary memory so the next step handler remembers it
        user_states[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%b %d')}**.\nWhat time will you wake up? *(HH:MM 24-hr, e.g. 06:30)*", parse_mode="Markdown")
        
        # This tells Telegram: "The very next text message this user sends should go to the 'process_plan_time' function"
        bot.register_next_step_handler(msg, process_plan_time)

    elif call.data == "plan_custom":
        user_states[chat_id] = {'action': 'plan'}
        msg = bot.send_message(chat_id, "Reply with date in `DD-MM-YYYY` format (e.g. 25-07-2026):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --------------------------------------------------
    # 3. CLEAR DAY MENU
    # --------------------------------------------------
    elif call.data == "clear_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="clear_today"), InlineKeyboardButton("Tomorrow", callback_data="clear_tomorrow"), InlineKeyboardButton("Custom Date", callback_data="clear_custom"))
        bot.send_message(chat_id, "Which day do you want to clear?", reply_markup=markup)

    elif call.data in ["clear_today", "clear_tomorrow"]:
        target_date = datetime.datetime.now(tz).date() if call.data == "clear_today" else datetime.datetime.now(tz).date() + datetime.timedelta(days=1)
        bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
        clear_day_events(chat_id, target_date, bot) # Calls the wipe function

    elif call.data == "clear_custom":
        user_states[chat_id] = {'action': 'clear'}
        msg = bot.send_message(chat_id, "Reply with date in `DD-MM-YYYY` format:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

    # --------------------------------------------------
    # 4. ADD TASK MENU
    # --------------------------------------------------
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

    # --------------------------------------------------
    # 5. SETTINGS / CONFIGURATION MENU
    # --------------------------------------------------
    elif call.data == "settings_menu":
        profile = get_user_profile(chat_id)
        mode_str = "ON (24-Hour Active)" if profile.get('mode_24h') else "OFF (Standard Windows Active)"
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("⏰ Configure Wake Windows", callback_data="set_windows"))
        markup.row(InlineKeyboardButton(f"🌐 24H Mode: {mode_str}", callback_data="toggle_24h"))
        markup.row(InlineKeyboardButton("📅 Capture Custom Template", callback_data="set_templates"))
        markup.row(InlineKeyboardButton("🗑️ Reset Settings & Logout", callback_data="reset_menu"))
        
        bot.send_message(chat_id, "⚙️ **Settings / Configure**\nCustomize your preferences below:", reply_markup=markup, parse_mode="Markdown")

    elif call.data == "toggle_24h":
        profile = get_user_profile(chat_id)
        # Flip the boolean value: if True make False, if False make True
        profile['mode_24h'] = not profile.get('mode_24h', False)
        update_user_profile(chat_id, profile)
        bot.send_message(chat_id, f"🌐 **24-Hour Mode** is now **{'ENABLED' if profile['mode_24h'] else 'DISABLED'}**.")

    elif call.data == "set_windows":
        msg = bot.send_message(chat_id, "1️⃣ What time does your **EARLIEST** wake window start?\n*(HH:MM format, e.g. 04:00)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_window_early)

    elif call.data == "set_templates":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Early", callback_data="edit_tpl_early"), InlineKeyboardButton("Normal", callback_data="edit_tpl_normal"), InlineKeyboardButton("Late", callback_data="edit_tpl_late"))
        bot.send_message(chat_id, "Which template slot do you want to capture and override?", reply_markup=markup)

    elif call.data.startswith("edit_tpl_"):
        slot = call.data.split("_")[2] # extracts 'early', 'normal', or 'late'
        user_states[chat_id] = {'editing_slot': slot}
        msg = bot.send_message(chat_id, f"Capturing custom tasks for **{slot.upper()}**.\nReply with the Google Calendar date you built it on (`DD-MM-YYYY`):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_template_date)

    # --------------------------------------------------
    # 6. RESET & LOGOUT SUB-MENU
    # --------------------------------------------------
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
        bot.send_message(chat_id, "🧹 Full profile wiped. The bot will now use the factory default `templates.json` on your next run.")

    elif call.data == "delete_account":
        delete_user_data(chat_id)
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        bot.send_message(
            chat_id, 
            f"🔴 **Account Data Deleted & Logged Out.**\nYour stored Google OAuth token and profile have been completely wiped from MongoDB.\n\nTo use the bot again, authorize here:\n\n👉 {auth_url}",
            parse_mode="Markdown"
        )


# ==========================================
# STEP HANDLERS (Functions that run after a user replies to a prompt)
# ==========================================

def process_custom_date(message):
    """Parses a manually typed date (DD-MM-YYYY) and routes to the correct action."""
    chat_id = str(message.chat.id)
    try:
        # Attempt to convert the text into a real date object
        target_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").date()
        
        # Check temporary memory to see WHY we asked for a date (plan, clear, or add)
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
        bot.send_message(chat_id, "❌ Invalid date format. Please restart from menu and use DD-MM-YYYY.")

def process_plan_time(message):
    """Catches the wake-up time for a custom planned day."""
    chat_id = str(message.chat.id)
    try:
        target_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        # Combine the saved date and the newly provided time into one datetime object
        target_datetime = datetime.datetime.combine(user_states[chat_id]['date'], target_time)
        
        bot.send_message(chat_id, f"Preparing schedule for {target_datetime.strftime('%b %d at %I:%M %p')}...")
        execute_schedule_creation(chat_id, target_datetime, bot)
        
        # Clean up temporary memory
        if chat_id in user_states: del user_states[chat_id]
    except Exception: 
        bot.send_message(chat_id, "❌ Invalid time format. Use HH:MM.")

def process_add_task_name(message):
    """Saves the name of a custom task and asks for the start time."""
    chat_id = str(message.chat.id)
    user_states[chat_id]['name'] = message.text
    msg = bot.send_message(chat_id, "Start time? *(HH:MM 24-hr, e.g. 14:30)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_task_time)

def process_add_task_time(message):
    """Saves the start time of a custom task and asks for the duration."""
    chat_id = str(message.chat.id)
    try:
        chosen_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        user_states[chat_id]['start_time'] = chosen_time
        msg = bot.send_message(chat_id, "Duration in hours? *(e.g. 1, 1.5, 2)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_duration)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid time format.")

def process_add_task_duration(message):
    """Final step to add a custom task. Calls Google Calendar API."""
    chat_id = str(message.chat.id)
    try:
        # Convert text to a float (e.g. "1.5")
        duration_hours = float(message.text.strip())
        data = user_states[chat_id]
        add_custom_task(chat_id, data['date'], data['name'], data['start_time'], duration_hours, bot)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid duration.")
    finally:
        # Always clean up memory
        if chat_id in user_states: del user_states[chat_id]

# --- WAKE WINDOW SETUP SEQUENCE ---
# This is a chain of 4 step handlers that run one after the other.
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
        
        # Save all 4 times into the database
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


# --- CUSTOM TEMPLATE MEMORY CAPTURE ---
def process_template_date(message):
    """
    Takes the provided date, triggers the smart 18-hour calendar scanner, 
    and saves the raw JSON template into the user's MongoDB profile.
    """
    chat_id = str(message.chat.id)
    try:
        date_str = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").strftime("%d-%m-%Y")
        slot = user_states[chat_id]['editing_slot']
        
        # Call the new 18-hour fetcher from calendar_service to lock the custom template into database memory
        fetch_and_save_custom_template(chat_id, slot, date_str, bot)
        
        del user_states[chat_id]
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid date format. Please restart from menu and use DD-MM-YYYY.")


# ==========================================
# BOT LAUNCHER
# ==========================================
def start_bot():
    """This function keeps the bot running 24/7 on the server."""
    print("🚀 Vector Workflows UI started.")
    
    # Force-delete any lingering webhooks that might block polling
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

    while True:
        try: 
            bot.polling(none_stop=True)
        except Exception as e: 
            # ACTUALLY PRINT THE ERROR TO THE LOGS
            print(f"❌ [CRITICAL POLLING ERROR] {e}") 
            time.sleep(5)