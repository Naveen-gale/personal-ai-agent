# Personal AI Agent — Gmail, Contacts, Calendar, Tasks & Reminders

A personal AI assistant built with **LangGraph**, **LangChain**, **Groq**, **Google Gmail API**, **Google People API**, **Google Calendar API**, **Google Tasks API**, and a **Persistent Scheduled Reminder Engine**. The implemented agent interface is a local terminal chat loop.

The assistant can read, summarize, draft, send, reply to, and organize emails; search and create contacts; manage calendar events and daily schedules; track Google Tasks; and deliver automated reminders via Telegram or Console with strict safety confirmations.

---

## Capabilities

1. **Search & Read Emails**: Natural language queries (`'Find unread emails'`, `'Emails from boss'`). Read full email bodies and summarize unread emails with clear sections:
   - Summary / Overview
   - Key Deadlines & Dates
   - Action Items & Requests
2. **Draft & Send Emails (With Confirmation)**: Prepare email drafts in Gmail without sending, or send emails and replies with preview and confirmation.
3. **Organize Emails**: Mark as read/unread, archive, move to trash (recoverable; never permanent delete), and manage labels.
4. **Google Contacts**: Search names through People API and match phone digits locally. Preview new contacts and require explicit confirmation before creating.
5. **Google Calendar**: Check today's schedule, search events, create events, reschedule, and cancel meetings with timezone-aware handling (`Asia/Kolkata` default) and confirmation safeguards.
6. **Google Tasks**: List pending/completed tasks, add tasks with date-level due dates, update tasks, and complete tasks with confirmation.
7. **Scheduled Reminder Engine**: Set one-time or recurring reminders (daily, weekly, every morning, etc.), list reminders, and cancel reminders backed by persistent SQLite storage with atomic concurrency claims and Telegram/Console delivery.
8. **Security Guardrails**:
   - Email content, calendar descriptions, and task notes are untrusted data (prompt injection defense).
   - Sensitive write/delete actions require human-in-the-loop confirmation.
   - Credentials and tokens are protected and never logged or exposed.
---

## Project Structure

```
personal-ai-agent/
├── .gitignore
├── README.md
├── agent/                          Python agent package
│   ├── __init__.py
│   ├── main.py                     CLI entry point (chat loop + confirmation flow)
│   ├── graph.py                    LangGraph workflow construction & tool registration
│   ├── state.py                    Agent state definition (MessagesState)
│   ├── requirements.txt            Python dependencies
│   ├── .env                        Groq API key and model config
│   ├── .env.example                Safe configuration template
│   ├── credentials.json            Google Cloud OAuth 2.0 client secrets
│   ├── token.json                  Shared authorized Google API token
│   │
│   ├── nodes/
│   │   ├── __init__.py
│   │   └── assistant_node.py       Groq LLM reasoning node + security system prompt
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── assistant_tools.py      General tools (e.g. get_current_datetime)
│   │   ├── gmail_tools.py          Validated Gmail tools with confirmation checks
│   │   ├── contacts_tools.py       Contact search and confirmed creation tools
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gmail_service.py        Direct Gmail API calls (search, MIME send, labels)
│   │   ├── contacts_service.py     Google People API search and creation
│   │   ├── calendar_service.py    Google Calendar API operations
│   │   ├── tasks_service.py       Google Tasks API operations
│   │   ├── reminder_service.py    Persistent SQLite reminder scheduling
│   │   └── reminder_worker.py     Background reminder delivery worker
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   └── gmail_auth.py           Shared Gmail and Contacts OAuth scopes
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_imports.py         Module import & tool registration tests
│       ├── test_graph.py           Graph compilation & tool binding tests
│       ├── test_gmail.py           Unit tests with mocks for tools & safeguards
│       ├── test_contacts_*.py      Mocked Contacts unit tests
│       ├── test_integration.py     Opt-in live Gmail integration tests
│       └── test_contacts_integration.py  Opt-in read-only live Contacts test
│
├── backend/                        Node.js package scaffold; no server source yet
└── frontend/                       React/Vite starter; not connected to the agent
```

The repository does **not** currently contain a web backend or a web UI for
agent operations. `backend/src/server.js` is absent, and the frontend is the
stock Vite starter. The five agent capability groups are implemented in the
Python CLI, not exposed through the web projects. This cleanup does not create
that missing web application.

---

## Setup & Quick Start

### 1. Verify your `.env` configuration

If `agent/.env` does not already exist, copy the example and fill in your own
values. Never overwrite an existing environment file:

```powershell
if (-not (Test-Path agent\.env)) {
    Copy-Item agent\.env.example agent\.env
} else {
    Write-Host "agent\.env already exists; edit it without replacing its contents."
}
```

At minimum, configure `GROQ_API_KEY` and `GROQ_MODEL`. Set the Google OAuth
credentials in `agent/credentials.json` locally; do not commit that file,
`agent/token.json`, or `agent/.env`.

Install dependencies:

```powershell
.\agent\.venv\Scripts\python.exe -m pip install -r agent\requirements.txt
```

### Google authorization

The shared token requests Gmail, Contacts, Calendar, and Tasks scopes.

To authorize or reauthorize the shared token with all scopes, run:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.auth.gmail_auth
```

This opens your browser. Log in with your Google account and click **Allow**.
The token is saved to `agent/token.json`; reauthorization is only performed
when explicitly requested by this command.

### 3. Run the Automated Tests

The requirements install includes `pytest`. Run the mocked test suite; live
Google API tests are skipped unless explicitly enabled:

```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent\tests\ -v
```

### Start the agent CLI

Start the interactive terminal chat loop:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.main
```

Run the persistent reminder worker in another terminal:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.services.reminder_worker
```

### Frontend/backend status

The frontend can be started as a Vite development page from `frontend`:

```powershell
Push-Location frontend
npm install
npm run dev
Pop-Location
```

It is still the Vite starter and is not connected to the agent. The backend
package has no server source, so there is currently no backend startup command.

---

## Example Natural-Language Commands

### Reading & Summarizing
- *"Show me my five latest inbox emails."*
- *"What unread emails do I have? Summarize them and tell me if there are any deadlines."*
- *"Read email with Message ID 18f..."*

### Drafting & Sending
- *"Draft an email to advisor@university.edu about thesis proposal deadline."*
- *"Send an email to colleague@example.com with subject Project Sync and body Let's meet at 10 AM tomorrow."*
  - The agent will display a preview and ask: *"Are you sure you want to send this email? (yes/no)"*
  - Reply *"yes"* to approve, or *"no"* to cancel.

### Replying
- *"Reply to email with Message ID 18f... saying Thank you, I will review this tonight."*
  - The agent will preview the reply and ask for your confirmation before sending.

### Organizing
- *"Mark email with ID 18f... as read."*
- *"Archive email with ID 18f..."*
- *"Create a label named 'Invoices' and apply it to email ID 18f..."*
- *"Move email ID 18f... to trash."*
  - Requires confirmation before moving to Trash.

### Contacts
- *"Find Alex Morgan in my contacts."*
- *"Find the contact whose phone number ends in 4567."*
- *"Add Alex Morgan with phone 15551234567 and email alex@example.com."*
  - The assistant must show the preview first and create the contact only after you explicitly approve it.

### Optional live Contacts integration test

The default suite uses mocks and does not access the real contact list. To run the explicitly opt-in, read-only authentication/search check, provide a query you choose:

```powershell
$env:RUN_GOOGLE_CONTACTS_INTEGRATION = "1"
$env:GOOGLE_CONTACTS_TEST_QUERY = "your test query"
.\agent\.venv\Scripts\python.exe -m pytest agent\tests\test_contacts_integration.py -v
```

The integration test requests only names, prints no contact details, and never
creates or changes contacts.

---

## Safeguards & Security Architecture

- **Confirmation gate**: Sensitive tool calls first return a preview. The CLI accepts only a separate `yes`/`confirm` response for the exact pending tool call; model-supplied confirmation arguments alone cannot authorize the action. This is a local CLI safeguard, not web authentication.
- **Never Permanently Deletes**: The agent uses `trash()`, never permanent `delete()`. Trashed emails can be recovered within 30 days from Gmail Trash.
- **Recipient Validation**: Recipient addresses are strictly validated for standard format. The agent will never guess or invent an address.
- **Prompt Injection Defense**: Email bodies and headers are treated as untrusted data. Instructions inside emails cannot execute tools, disclose secrets, or alter system behavior.
- **Secrets Protection**: `.env`, `credentials.json`, and `token.json` are strictly excluded from version control in `.gitignore`.
- **Credential exposure**: If an OAuth client secret or token was exposed, manually revoke the exposed OAuth grant and rotate the OAuth client secret in Google Cloud Console, replace the local credentials file, and reauthorize. This project does not rotate or revoke credentials automatically.

## Known limitations

- There is no web API, user/session authentication, CSRF protection, or connected
  web UI. The existing Node and React folders are scaffolds, not a deployable
  application.
- Reminder delivery requires the separate worker process. The default
  notification channel is Telegram; Console delivery is available for local
  development. Claims prevent concurrent workers from processing the same
  reminder, but delivery is at-least-once: a worker or network failure after
  remote delivery but before the database is updated may cause a retry.
- Live Google integrations were not run as part of the default test suite.
