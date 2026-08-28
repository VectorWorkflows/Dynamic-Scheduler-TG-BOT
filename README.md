<div align="center">

<br />

<pre>
██████╗ ██╗   ██╗███╗   ██╗ █████╗ ███╗   ███╗██╗ ██████╗
██╔══██╗╚██╗ ██╔╝████╗  ██║██╔══██╗████╗ ████║██║██╔════╝
██║  ██║ ╚████╔╝ ██╔██╗ ██║███████║██╔████╔██║██║██║     
██║  ██║  ╚██╔╝  ██║╚██╗██║██╔══██║██║╚██╔╝██║██║██║     
██████╔╝   ██║   ██║ ╚████║██║  ██║██║ ╚═╝ ██║██║╚██████╗
╚═════╝    ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚═════╝
</pre>

### DYNAMIC SCHEDULER

**A Telegram bot that turns "I just woke up" into a fully-built Google Calendar day.**

<sub>by <a href="https://vectorworkflows.com"><b>VECTOR WORKFLOWS</b></a> — precision-engineered automation</sub>

<br />

[![Python](https://img.shields.io/badge/PYTHON-3.11+-000000?style=for-the-badge&logo=python&logoColor=00D9FF)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FASTAPI-OAuth_Engine-000000?style=for-the-badge&logo=fastapi&logoColor=00D9FF)](https://fastapi.tiangolo.com/)
[![Telegram](https://img.shields.io/badge/TELEGRAM-Bot_API-000000?style=for-the-badge&logo=telegram&logoColor=00D9FF)](https://core.telegram.org/bots)
[![MongoDB](https://img.shields.io/badge/MONGODB-Persistence-000000?style=for-the-badge&logo=mongodb&logoColor=00D9FF)](https://www.mongodb.com/)
[![License](https://img.shields.io/badge/LICENSE-MIT-000000?style=for-the-badge&logoColor=00D9FF)](#license)

<br />

`awake_now` → `calendar populated` → `you never think about your schedule again`

<br />

</div>

<br />

## ▍ What is this

Most calendar apps make you *build* your day. This one asks you a single question — **"what time did you wake up?"** — and reverse-engineers the rest.

Tell the bot you woke up at 7:40 AM. It looks at the clock, decides which block of your day you're currently in, and writes the remainder of that day straight into your **Google Calendar** — work blocks, workouts, meals, wind-down — timestamped, colored, and already running. Wake up late? It adapts. Live a life with no fixed wake time? Flip on **24-Hour Mode** and pick your own rhythm on demand.

No spreadsheets. No manual event creation. No "I'll plan it later" that never happens.

<br />

## ▍ How it actually works

<div align="center">

```
┌──────────────┐        ┌───────────────────┐        ┌──────────────────┐
│   TELEGRAM   │  tap   │   DYNAMIC ENGINE   │  push  │  GOOGLE CALENDAR  │
│  /menu  🤖   │ ─────► │  time → template   │ ─────► │  event  ×N  📅    │
└──────────────┘        └───────────────────┘        └──────────────────┘
       ▲                          │
       │                          ▼
       │                 ┌───────────────────┐
       └──────────────── │      MONGODB       │
         auth + profile  │  tokens · presets   │
                          └───────────────────┘
```

</div>

1. **You authenticate once.** `/start` hands you a link into a FastAPI OAuth engine, which walks you through Google's consent screen and locks your refresh token safely in MongoDB — you never see it again after that.
2. **You tell it when your day begins.** Tap **🌅 Awake Now**, or let 24-Hour Mode ask whether this is an *early*, *normal*, or *late* start.
3. **The engine picks a template.** `determine_dynamic_template()` maps your wake time against your saved routines (`normal`, `early`, `late`, or your own custom presets) and slices out only the blocks still ahead of you.
4. **Your calendar fills itself in.** Every block is pushed to Google Calendar as a real, colored, timed event — ready before you've finished your coffee.

<br />

## ▍ Inside the menu

<table>
<tr><td width="26%"><b>🌅 Awake Now</b></td><td>Reads the current time (or your manual pick in 24H mode) and instantly builds out the rest of today.</td></tr>
<tr><td><b>🗓️ Plan</b></td><td>Pre-build <i>today</i> or <i>tomorrow</i> in advance — or hand-pick a custom date.</td></tr>
<tr><td><b>➕ Add Task</b></td><td>Drop a one-off task into any day without touching your routine template.</td></tr>
<tr><td><b>🧹 Clear Day</b></td><td>Wipe every bot-created event off a given day — today, tomorrow, or custom — in one tap.</td></tr>
<tr><td><b>⚙️ Settings</b></td><td>Toggle 24-Hour Mode, redefine your wake-time windows, or edit the <code>early</code> / <code>normal</code> / <code>late</code> templates directly from chat.</td></tr>
<tr><td><b>♻️ Reset</b></td><td>Roll back your wake-windows, factory-reset your whole profile, or fully delete your account and stored tokens.</td></tr>
</table>

<br />

## ▍ Stack

<div align="center">

| Layer | Technology |
|:--|:--|
| **Bot interface** | `pyTelegramBotAPI` — inline keyboards, callback routing, conversational state |
| **Auth server** | `FastAPI` + `uvicorn` — runs Google's OAuth2 / PKCE handshake over HTTPS |
| **Calendar engine** | `google-api-python-client` — reads, writes, and clears Calendar events |
| **Persistence** | `MongoDB` (`pymongo`) — user tokens, profiles, wake-windows, custom templates |
| **Scheduling logic** | Pure Python, timezone-aware via `pytz` | 

</div>

<br />

## ▍ Get it running

```bash
# 1 — clone
git clone https://github.com/VectorWorkflows/Dynamic-Scheduler-TG-BOT.git
cd Dynamic-Scheduler-TG-BOT

# 2 — install
pip install -r requirements.txt

# 3 — configure
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN, MONGO_URI, BASE_URL, USER_TIMEZONE

# 4 — bring your own Google OAuth client
# drop your Google Cloud "Desktop/Web" credentials.json in the project root

# 5 — launch
python main.py
```

<details>
<summary><b>Environment variables</b></summary>

<br />

| Variable | Purpose |
|:--|:--|
| `TELEGRAM_BOT_TOKEN` | Your bot's token from [@BotFather](https://t.me/BotFather) |
| `GOOGLE_CREDENTIALS_PATH` | Path to your Google OAuth `credentials.json` |
| `MONGO_URI` | MongoDB connection string for token & profile storage |
| `BASE_URL` | Public URL of your deployed OAuth server (used in the `/callback` redirect) |
| `USER_TIMEZONE` | Default IANA timezone, e.g. `Asia/Kolkata` |
| `PORT` | Port for the FastAPI server (defaults to `8080`) |

</details>

The FastAPI app and the Telegram bot boot together from `main.py` — the bot runs on a background thread, the OAuth server owns the main thread and exposes `/health`, `/login`, and `/callback`. Ship it anywhere that can hold a long-lived process: Render, Railway, Fly.io, a VPS, a Docker container.

<br />

## ▍ Repository map

```
Dynamic-Scheduler-TG-BOT/
├── main.py                  → FastAPI server + OAuth flow + process launcher
├── config.py                → Environment & path configuration
├── templates.json           → Default early / normal / late day templates
├── requirements.txt
└── src/
    ├── bot.py                → All Telegram handlers, menus & callbacks
    ├── calendar_service.py   → Template logic + Google Calendar read/write
    └── database.py           → MongoDB models for tokens & user profiles
```

<br />

## ▍ Philosophy

Vector Workflows builds automation that disappears into the background — the best interface is the one you stop noticing. This bot exists so that **"plan my day"** stops being a task on your to-do list, and starts being something that's just already done.

<br />

---

<div align="center">

<sub>Crafted by <a href="https://vectorworkflows.com"><b>Vector Workflows</b></a></sub>

<sub>MIT Licensed — build on it, fork it, make it yours.</sub>

</div>
