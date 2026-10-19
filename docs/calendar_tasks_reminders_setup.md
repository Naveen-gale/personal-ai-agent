# Google Calendar, Google Tasks & Automated Reminders Setup Guide

This guide details the complete configuration and usage of the **Google Calendar**, **Google Tasks**, and **Automated Reminder Engine** in your Personal AI Agent.

---

## 1. Google APIs to Enable

In your [Google Cloud Console](https://console.cloud.google.com/):
1. Navigate to **APIs & Services > Library**.
2. Search and click **Enable** for each of the following:
   - **Google Calendar API**
   - **Google Tasks API**
   - **Gmail API** (already enabled)
   - **Google People API** (already enabled for Contacts)

---

## 2. OAuth Scopes & Permissions

The agent uses a single unified OAuth 2.0 desktop token (`agent/token.json`) covering:
- **Gmail:** `https://www.googleapis.com/auth/gmail.modify`
- **Contacts:** `https://www.googleapis.com/auth/contacts.readonly`, `https://www.googleapis.com/auth/contacts`
- **Calendar:** `https://www.googleapis.com/auth/calendar.events`
- **Tasks:** `https://www.googleapis.com/auth/tasks`

### When Reauthorization is Required
Because Calendar and Tasks introduce new OAuth scopes, your existing token must be refreshed with the new permissions once.

**Run the authorization helper:**
```powershell
.\agent\.venv\Scripts\python.exe -m agent.auth.gmail_auth
```
- A browser window will open.
- Sign in and click **Allow** for the requested Calendar, Tasks, Gmail, and Contacts permissions.
- The updated token is automatically written to `agent/token.json`.
- *Note:* Existing Gmail and Contacts operations will continue to work even before you reauthorize, but Calendar and Tasks API calls will prompt you to run this reauthorization until granted.

---

## 3. Environment Variables (`agent/.env`)

Add or verify the following configuration in your `agent/.env` file:

```dotenv
# Groq LLM Configuration
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Timezone (Default: Asia/Kolkata / IST, UTC+05:30)
USER_TIMEZONE=Asia/Kolkata

# Scheduled Reminders Storage (Default: agent/reminders.db)
REMINDERS_DB_PATH=agent/reminders.db

# Optional: Telegram Delivery Adapter Configuration
# Create a bot via @BotFather on Telegram to get your BOT_TOKEN
# Get your numerical Chat ID via @userinfobot
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## 4. Architecture & Safeguards Overview

```
User Query (e.g. "Schedule meeting tomorrow at 10 AM")
   │
   ▼
main.py (Chat loop with sliding history & Windows UTF-8 stdout)
   │
   ▼
LangGraph Agent (graph.py)
   ├── nodes/assistant_node.py (Groq LLM + Anti-looping system prompt)
   └── ToolNode (30 Tools Registered)
        ├── tools/gmail_tools.py (12 email tools)
        ├── tools/contacts_tools.py (2 contact tools)
        ├── tools/calendar_tools.py (6 calendar tools)
        ├── tools/tasks_tools.py (6 tasks tools)
        ├── tools/reminder_tools.py (3 reminder tools)
        └── tools/assistant_tools.py (1 date/time tool)
```

### Safety & Safeguards (Preview Before Execution)
Every write or destructive operation follows a strict **two-step confirmation workflow**:
1. **First Invocation (`confirmed=False`):** The tool returns a structured preview of the exact changes, timestamps in `Asia/Kolkata`, and prompts the user for approval.
2. **Second Invocation (`confirmed=True`):** Only after the user confirms (e.g. typing `yes`), the agent executes the real API call or database write.

| Operation | Tool Name | Requires Confirmation? | Safeguard Detail |
|---|---|:---:|---|
| **View Today's Events** | `get_today_events` | No | Read-only |
| **List / Search Events** | `list_calendar_events`, `search_calendar_events` | No | Read-only |
| **Create Event** | `create_calendar_event` | **YES** | Previews start, end, title; validates end > start |
| **Update / Reschedule Event** | `update_calendar_event` | **YES** | Previews current vs proposed start/end/title |
| **Cancel Event** | `delete_calendar_event` | **YES** | Identifies specific event before deletion |
| **List Tasks** | `list_pending_tasks`, `list_completed_tasks` | No | Read-only |
| **Create Task** | `create_task` | **YES** | Previews title, notes, due date |
| **Complete Task** | `complete_task` | **YES** | Confirms marking task completed |
| **Delete Task** | `delete_task` | **YES** | Confirms permanent removal from Google Tasks |
| **Create Reminder** | `create_reminder` | **YES** | Validates future timestamp; resolves timezone |
| **Cancel Reminder** | `cancel_reminder` | **YES** | Previews reminder before cancellation |

> [!NOTE]
> **Google Tasks vs Scheduled Reminders:** Google Tasks due dates have date-level semantics (RFC 3339 timestamp formatted to `00:00:00.000Z`). For precise, minute-level notifications (e.g. *"Remind me at 7 PM"*), use the **Scheduled Reminder Engine**.

---

## 5. Starting the Scheduled Reminders Worker

The reminder scheduler runs as a separate background process so it never blocks conversational request handling:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.services.reminder_worker
```

### Features of the Reminder Engine
- **Persistent SQLite Storage:** Backed by `agent/reminders.db` with WAL mode enabled.
- **Concurrency-Safe Atomic Claims:** Multiple worker instances or restarts will never send duplicate notifications (`UPDATE reminders SET status = 'claimed' WHERE status = 'pending'`).
- **Crash Recovery:** If the worker crashes mid-tick, stale claimed reminders (> 5 minutes) are automatically recovered on the next tick.
- **Recurring Reminders:** Automatically calculates and inserts the next occurrence in `Asia/Kolkata` upon delivery (e.g., `daily`, `weekly`, `every_morning:09:00`, `every_evening:20:00`).
- **Delivery Adapters:**
  - **Telegram:** Delivers instant push messages to your phone via Telegram Bot API with exponential retry backoff.
  - **Console:** Local fallback mode that prints reminders directly to stdout for development or offline testing.

---

## 6. How to Run the Assistant & Tests

### Start the Interactive Terminal Chat Loop
```powershell
.\agent\.venv\Scripts\python.exe -m agent.main
```

### Run the Complete Test Suite (149 Unit Tests)
```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent\tests\ -v
```

---

## 7. Natural-Language Command Examples

### Google Calendar
- *"What is on my calendar today?"*
- *"Show my schedule for tomorrow."*
- *"Find my next meeting."*
- *"Schedule a meeting tomorrow at 10 AM for 30 minutes with subject Team Sync."*
- *"Reschedule my meeting to 4 PM."*
- *"Cancel the Design Review meeting."*

### Google Tasks
- *"Show my pending tasks."*
- *"Add a task to complete my assignment by Friday."*
- *"Show completed tasks."*
- *"Mark my assignment complete."*
- *"Delete task <task_id>."*

### Scheduled Reminders
- *"Remind me to study Python tomorrow at 7 PM."*
- *"Remind me every day at 9 AM to review pull requests."*
- *"Remind me in 30 minutes to drink water."*
- *"Show my scheduled reminders."*
- *"Cancel reminder <reminder_id>."*

---

## 8. Security & Keeping Credentials Safe

- `credentials.json` and `token.json` are strictly excluded from version control via `.gitignore`.
- Secrets are loaded exclusively from `agent/.env`.
- Descriptions in calendar events and task notes are treated as untrusted content; the agent never executes instructions found within them.

