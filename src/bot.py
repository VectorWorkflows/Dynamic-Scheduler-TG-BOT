import time
import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from src.database import get_user_token
from src.calendar_service import execute_schedule_creation, clear_day_events, add_custom_task, tz

bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
user_planning_data = {}

def is_authenticated(chat_id: str) -> bool:
    return get_user_token(chat_id) is not None
@bot.message_handler(commands=['start', 'menu'])
def send_menu(message):
    chat_id = str(message.chat.id)
    
    # Check if the user is logged in
    if not is_authenticated(chat_id):
        auth_url = f"{config.BASE_URL}/login?chat_id={chat_id}"
        
        # We send raw text without Markdown or Buttons so Telegram doesn't block localhost
        bot.send_message(
            chat_id, 
            f"👋 Welcome to Vector Workflows!\n\nTelegram blocks local testing links, so please COPY and PASTE this exact URL into your browser to connect Google Calendar:\n\n{auth_url}"
        )
        return

    # If they ARE logged in, show the full menu
    markup = InlineKeyboardMarkup()
    btn_awake = InlineKeyboardButton("🌅 Awake Now", callback_data="awake_now")
    btn_plan = InlineKeyboardButton("🗓️ Plan", callback_data="plan_menu")
    btn_add = InlineKeyboardButton("➕ Add Task", callback_data="add_task_menu")
    btn_clear = InlineKeyboardButton("🧹 Clear Day", callback_data="clear_menu")
    
    markup.row(btn_awake, btn_plan)
    markup.row(btn_add, btn_clear)
    
    bot.send_message(chat_id, "🤖 **Main Menu**\nChoose a mode:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = str(call.message.chat.id)
    
    if not is_authenticated(chat_id):
        bot.send_message(chat_id, f"🔒 Please login first:\n{config.BASE_URL}/login?chat_id={chat_id}")
        return

    # --- AWAKE NOW ---
    if call.data == "awake_now":
        now = datetime.datetime.now(tz).replace(tzinfo=None)
        bot.send_message(chat_id, f"Processing current time: {now.strftime('%I:%M %p')}...")
        execute_schedule_creation(chat_id, now, bot)
        
    # --- PLAN MENU ---
    elif call.data == "plan_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="plan_today"),
                   InlineKeyboardButton("Tomorrow", callback_data="plan_tomorrow"),
                   InlineKeyboardButton("Custom", callback_data="plan_custom"))
        bot.send_message(chat_id, "Which day are you planning for?", reply_markup=markup)
        
    elif call.data in ["plan_today", "plan_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "plan_today" else current_date + datetime.timedelta(days=1)
        user_planning_data[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%A, %b %d')}**.\n\nWhat time do you plan to wake up?\n*(Reply with 24-hour format, e.g., 04:15, 08:30)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_plan_time)

    # --- CLEAR MENU ---
    elif call.data == "clear_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="clear_today"),
                   InlineKeyboardButton("Tomorrow", callback_data="clear_tomorrow"),
                   InlineKeyboardButton("Custom", callback_data="clear_custom"))
        bot.send_message(chat_id, "Which day do you want to completely clear?", reply_markup=markup)

    elif call.data in ["clear_today", "clear_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "clear_today" else current_date + datetime.timedelta(days=1)
        bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
        clear_day_events(chat_id, target_date, bot)

    # --- ADD TASK MENU ---
    elif call.data == "add_task_menu":
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Today", callback_data="add_today"),
                   InlineKeyboardButton("Tomorrow", callback_data="add_tomorrow"),
                   InlineKeyboardButton("Custom", callback_data="add_custom"))
        bot.send_message(chat_id, "When is this task for?", reply_markup=markup)

    elif call.data in ["add_today", "add_tomorrow"]:
        current_date = datetime.datetime.now(tz).date()
        target_date = current_date if call.data == "add_today" else current_date + datetime.timedelta(days=1)
        user_planning_data[chat_id] = {'date': target_date}
        msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%A, %b %d')}**.\n\nWhat is the name of the task/event?", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_name)

    # --- CUSTOM DATES ---
    elif call.data in ["plan_custom", "clear_custom", "add_custom"]:
        action = call.data.split('_')[0]
        user_planning_data[chat_id] = {'action': action}
        msg = bot.send_message(chat_id, "Please reply with the date in `DD-MM-YYYY` format (e.g., 25-07-2026):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_custom_date)

def process_custom_date(message):
    chat_id = str(message.chat.id)
    try:
        target_date = datetime.datetime.strptime(message.text.strip(), "%d-%m-%Y").date()
        action = user_planning_data.get(chat_id, {}).get('action')
        
        if action == "plan":
            user_planning_data[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Planning for **{target_date.strftime('%A, %b %d')}**.\n\nWhat time do you plan to wake up?\n*(Reply with 24-hour format, e.g., 04:15, 08:30)*", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_plan_time)
            
        elif action == "clear":
            bot.send_message(chat_id, f"🧹 Sweeping all events for {target_date.strftime('%b %d')}...")
            clear_day_events(chat_id, target_date, bot)
            if chat_id in user_planning_data: del user_planning_data[chat_id]
                
        elif action == "add":
            user_planning_data[chat_id] = {'date': target_date}
            msg = bot.send_message(chat_id, f"Adding task for **{target_date.strftime('%A, %b %d')}**.\n\nWhat is the name of the task/event?", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_add_task_name)
            
        else:
            bot.send_message(chat_id, "❌ Session expired. Please tap /menu to start over.")
            
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid format. Please use DD-MM-YYYY (e.g., 25-07-2026). Tap /menu to try again.")

def process_plan_time(message):
    chat_id = str(message.chat.id)
    try:
        chosen_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        chosen_date = user_planning_data[chat_id]['date']
        target_datetime = datetime.datetime.combine(chosen_date, chosen_time)
        
        bot.send_message(chat_id, f"Excellent. Preparing schedule for {target_datetime.strftime('%b %d at %I:%M %p')}...")
        execute_schedule_creation(chat_id, target_datetime, bot)
        if chat_id in user_planning_data: del user_planning_data[chat_id]
        
    except (ValueError, KeyError):
        bot.send_message(chat_id, "❌ Error parsing time or memory lost. Tap /menu to try again.")

def process_add_task_name(message):
    chat_id = str(message.chat.id)
    user_planning_data[chat_id]['name'] = message.text
    msg = bot.send_message(chat_id, "What time does it start?\n*(24-hour format, e.g. 14:30)*", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_task_time)

def process_add_task_time(message):
    chat_id = str(message.chat.id)
    try:
        chosen_time = datetime.datetime.strptime(message.text.strip(), "%H:%M").time()
        user_planning_data[chat_id]['start_time'] = chosen_time
        msg = bot.send_message(chat_id, "How long is it?\n*(In hours, e.g. 1, 1.5, 2)*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_task_duration)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid time format. Use /menu to restart.")

def process_add_task_duration(message):
    chat_id = str(message.chat.id)
    try:
        duration_hours = float(message.text.strip())
        data = user_planning_data[chat_id]
        add_custom_task(chat_id, data['date'], data['name'], data['start_time'], duration_hours, bot)
    except ValueError:
        bot.send_message(chat_id, "❌ Invalid duration. Use /menu to restart.")
    finally:
        if chat_id in user_planning_data: del user_planning_data[chat_id]

def start_bot():
    print("🚀 Vector Workflows UI started. Listening for buttons 24/7...")
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"⚠️ Telegram Error: {e}")
            time.sleep(5)