# Personal AI Agent — Gmail, Drive, Photos, Contacts, Calendar, Tasks, Reminders & Workflow Automation

A production-grade, extensible personal AI assistant built with **LangGraph**, **LangChain**, **Groq**, **Google Gmail API**, **Google Drive API**, **Google Photos Picker API**, **Google People API**, **Google Calendar API**, **Google Tasks API**, a **Persistent Scheduled Reminder Engine**, and a **Workflow Automation System** with a **React Web Dashboard** and **FastAPI REST API**.

The assistant can read, summarize, draft, send, reply to, and organize emails; browse, search, import, upload, and organize Google Drive files; select Google Photos media through the Picker API; search and create contacts; manage calendar events and daily schedules; track Google Tasks; deliver automated reminders via Telegram or Console; and compose, execute, schedule, and monitor multi-step workflows with human confirmation safeguards.

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
8. **Workflow Automation Engine**:
   - Multi-step structured workflows with dependencies, templating (`{{step_1.output}}`, `{{all_outputs}}`), and safe conditional branching (`{{step_1.count}} > 0`).
   - Trigger options: Manual (on-demand), Scheduled (daily, weekly, interval via `Asia/Kolkata` timezone), and Event-driven.
   - Built-in AI step synthesizer tool (`llm_synthesize`) to summarize, extract, and draft content across workflow steps.
   - Concurrency-safe atomic database claims preventing duplicate scheduled executions across restarts.
   - Human-in-the-loop approval gate for sensitive operations (sending email, deleting events/tasks).
   - Pre-seeded with "Morning Daily Overview" (8:00 AM) and "Evening Daily Review & Planner" (7:00 PM).
9. **Independently Deployable Web Services**:
   - **Frontend**: React (Vite) dashboard with Google Sign-In and an in-memory bearer session.
   - **Central Backend**: FastAPI service responsible for Google identity verification, user authorization, MongoDB persistence, request IDs, consistent API errors, and authenticated service-to-service calls.
   - **Agent Service**: Private FastAPI service for LangGraph and Google integrations, accessible only with the backend's shared service credential.
   - **MongoDB**: Stores users, conversations, messages, chat executions, and owner-scoped approvals.
10. **Drive & Photos**: Browse and search Drive, import supported text and PDF content into chat, upload local files, create folders, rename/move/copy files, and move items to trash with confirmation. Select Photos media using the official Picker flow and save selected items into Drive.
11. **Security Guardrails**:
    - Email content, calendar descriptions, and task notes are untrusted data (prompt injection defense).
    - Sensitive write/delete actions require human-in-the-loop confirmation.
    - Untrusted code execution is blocked: workflows only invoke whitelisted tool adapters.
    - Credentials and tokens are protected and never logged or exposed.

---

## Project Structure

```text
personal-ai-agent/
├── README.md
├── agent/                          Python agent package
│   ├── __init__.py
│   ├── main.py                     CLI entry point (chat loop + confirmation flow)
│   ├── api.py                      FastAPI REST server (/api/workflows, /api/chat, etc.)
│   ├── graph.py                    LangGraph workflow construction & registered tools
│   ├── state.py                    Agent state definition (MessagesState)
│   ├── requirements.txt            Python dependencies (LangGraph, FastAPI, Groq, Google APIs)
│   ├── .env                        Groq API key and model config
│   ├── .env.example                Safe configuration template
│   ├── credentials.json            Google Cloud OAuth 2.0 client secrets
│   ├── token.json                  Shared authorized Google API token
│   ├── reminders.db                SQLite storage for reminders
│   ├── workflows.db                Legacy SQLite migration source/backup
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
│   │   ├── calendar_tools.py       Google Calendar management tools
│   │   ├── tasks_tools.py          Google Tasks operations tools
│   │   ├── reminder_tools.py       Scheduled reminder tools
│   │   ├── workflow_tools.py       LangChain workflow creation, run, pause, history tools
│   │   └── drive_tools.py          Google Drive browsing and confirmed management tools
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gmail_service.py        Direct Gmail API calls (search, MIME send, labels)
│   │   ├── contacts_service.py     Google People API search and creation
│   │   ├── calendar_service.py     Google Calendar API operations
│   │   ├── tasks_service.py        Google Tasks API operations
│   │   ├── drive_service.py        Drive listing, extraction, resumable upload and file management
│   │   ├── photos_picker_service.py Picker session and selected-media transfer
│   │   ├── reminder_service.py     Persistent SQLite reminder scheduling
│   │   ├── reminder_worker.py      Background reminder delivery worker
│   │   ├── workflow_service.py     MongoDB workflow persistence (SQLite test/legacy mode)
│   │   ├── workflow_adapters.py    Whitelisted tool registry & LLM synthesizer adapter
│   │   ├── workflow_engine.py      Sequential runner, template resolver, approval pause/resume
│   │   └── workflow_scheduler.py   Background scheduler daemon with atomic claim concurrency
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   └── gmail_auth.py           Shared OAuth token manager for Google APIs
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_imports.py         Module imports and tool registration tests
│       ├── test_graph.py           Graph compilation & tool binding tests
│       ├── test_workflow_engine.py Engine sequencing, branching & approval tests
│       ├── test_workflow_scheduler.py Scheduler concurrency, recurrence & ticks
│       ├── test_workflow_api.py    FastAPI endpoints integration tests
│       ├── test_workflow_chat_tools.py LangChain chat tool invocation tests
│       ├── test_drive_api.py       Drive API and web confirmation tests
│       ├── test_drive_service.py   Mocked Drive API service tests
│       └── test_photos_picker_service.py Mocked Photos Picker tests
│
├── backend/                        Public FastAPI backend (independent deployment)
│   ├── app/
│   │   ├── main.py                 Authenticated API, MongoDB persistence and agent proxy
│   │   ├── security.py             Google ID-token and backend-session verification
│   │   ├── database.py             MongoDB lifecycle and indexes
│   │   └── config.py               Validated environment configuration
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/                       React + Vite Web UI
    ├── src/
    │   ├── App.jsx                 Dashboard container, tab router & dark UI theme
    │   ├── components/
    │   │   ├── Navbar.jsx          Navigation, active tab switcher & health status pill
    │   │   ├── WorkflowList.jsx    Workflow dashboard cards, run/pause triggers
    │   │   ├── WorkflowDetailModal.jsx Ordered step inspector & execution history log
    │   │   ├── WorkflowCreateModal.jsx Visual builder & natural language prompt generator
    │   │   ├── ApprovalsBanner.jsx Human-in-the-loop review cards (Approve / Reject)
    │   │   ├── ChatTab.jsx         Interactive agent chat with LangGraph
    │   │   └── DrivePanel.jsx      Drive browser, uploads and Photos Picker workflow
    │   └── App.css                 Modern clean responsive styling
    └── vite.config.js              Development proxy to the central backend
```

---

## Setup & Quick Start

### 1. Verify your `.env` configuration

Ensure `agent/.env` contains your Groq API credentials:

```powershell
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
TIMEZONE=Asia/Kolkata
```

### 2. Google OAuth Authorization

The shared token requests Gmail, Contacts, Calendar, Tasks, Google Drive, and
Google Photos Picker scopes. Reauthorize after enabling the APIs and adding
these scopes to the Google OAuth consent configuration:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.auth.gmail_auth
```

### 3. Run the Automated Tests

Run the entire unit and integration test suite:

```powershell
.\agent\.venv\Scripts\python.exe -m pytest agent\tests\ -v
```

---

## Running the Application

For the web dashboard, run the central backend, private agent service, and
frontend as described in [Independent service deployment](#independent-service-deployment).
Start the workflow scheduler in a separate agent process when scheduled
workflows are enabled:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.services.workflow_scheduler
```

Open `http://localhost:5173` and sign in with the configured Google account.

---

### Option B: Terminal CLI Interface

You can also use the assistant completely from PowerShell terminal:

1. **Start Interactive Agent CLI**:
   ```powershell
   .\agent\.venv\Scripts\python.exe -m agent.main
   ```

2. **Start Background Reminder Worker**:
   ```powershell
   .\agent\.venv\Scripts\python.exe -m agent.services.reminder_worker
   ```

---

## Workflow Automation System

### Available Workflow Tools
Workflows execute strictly within a whitelisted registry defined in `agent/services/workflow_adapters.py`:
- `get_unread_emails`: Fetch and inspect unread Gmail messages.
- `search_gmail`: Query Gmail messages.
- `create_draft`: Create an email draft in Gmail.
- `send_email`: Send an email (requires human approval).
- `get_today_events`: Retrieve Google Calendar events for today.
- `list_calendar_events`: List events within date bounds.
- `create_calendar_event`: Schedule calendar meeting.
- `delete_calendar_event`: Remove event (requires human approval).
- `list_pending_tasks`: Retrieve uncompleted Google Tasks.
- `create_task`: Add a new task with due date.
- `complete_task`: Mark task completed.
- `delete_task`: Remove task (requires human approval).
- `create_reminder`: Schedule a reminder.
- `list_reminders`: Inspect pending reminders.
- `find_contact`: Search contact details.
- `llm_synthesize`: AI synthesis tool to generate executive summaries, action item lists, or draft messages from previous step outputs.

### Natural-Language Workflow Commands
You can create, trigger, and inspect workflows via natural language in CLI or Web Chat:
- *"Create a workflow called 'Morning Briefing' that runs every day at 8:00 AM, checks today's calendar events, lists pending tasks, and synthesizes a morning plan."*
- *"Show all my automated workflows."*
- *"Run workflow 'Morning Daily Overview' now."*
- *"Pause workflow 'Evening Daily Review & Planner'."*
- *"Resume workflow 'Evening Daily Review & Planner'."*
- *"Show execution history for 'Morning Daily Overview'."*
- *"Retry the last failed workflow."*

### REST API Reference
- `POST /api/v1/auth/google`: Verify a Google ID credential and issue a short-lived backend bearer token.
- `GET /api/v1/me`: Return the currently authenticated owner.
- `GET|POST /api/v1/conversations`: List or create the owner's MongoDB-backed conversations.
- `GET /api/v1/conversations/{id}/messages`: Read messages for an owned conversation.
- `DELETE /api/v1/conversations/{id}`: Delete an owned conversation and its related chat records.
- `POST /api/v1/chat`: Persist a chat turn and execution using the supplied `idempotency_key`.
- `POST /api/v1/chat/confirm`: Resolve an owner-scoped, MongoDB-backed chat approval.
- `GET /api/v1/approvals`: List pending chat approvals.
- `GET /api/v1/executions`: List persisted chat executions.
- Legacy `/api/*` workflow and Drive endpoints are authenticated by the central backend and proxied to the private agent.

All endpoints other than health/readiness and Google sign-in require
`Authorization: Bearer <access_token>`. Errors use the standard
`{success:false,error:{code,category,message,retryable,details,request_id}}`
shape; legacy proxy errors also include `detail` for compatibility.

- `GET /api/health`: Health status.
- `GET /api/tools`: Whitelisted workflow tool registry and JSON schemas.
- `GET /api/workflows`: List all workflows (`?status=active|paused`).
- `POST /api/workflows`: Create and validate a new workflow.
- `GET /api/workflows/{id}`: Get workflow definition.
- `PUT /api/workflows/{id}`: Update workflow name, trigger, or steps.
- `DELETE /api/workflows/{id}`: Delete workflow.
- `POST /api/workflows/{id}/run`: Manually trigger a workflow run.
- `POST /api/workflows/{id}/pause`: Pause scheduled runs.
- `POST /api/workflows/{id}/resume`: Resume scheduled runs.
- `GET /api/executions`: List recent executions across all workflows.
- `GET /api/executions/{id}`: Detailed step results, timeline, and error logs.
- `POST /api/executions/{id}/approve`: Approve or reject a pending approval step (`{"decision": "approved"}`).
- `POST /api/executions/{id}/retry`: Retry a failed execution.
- `GET /api/approvals`: List all pending human-in-the-loop approvals.
- `POST /api/chat`: Send a message to the LangGraph AI agent.

---

## Safeguards & Security Architecture

- **Confirmation Gate**: Sensitive actions (sending emails, deleting tasks, deleting calendar meetings) require human approval before execution. In CLI, this is enforced by an explicit user prompt. In the Workflow Engine, execution pauses in state `pending_approval` until approved via API or Web UI banner.
- **Whitelist Enforcement**: Workflows can only execute registered adapter functions. No arbitrary code execution (`eval`, `exec`) is allowed.
- **Safe Condition Parser**: Conditional branching uses structured regex operator comparison instead of Python `eval()`, preventing remote code execution vulnerabilities.
- **Atomic Concurrency**: Scheduled workflows and reminders use atomic database transactions (`UPDATE ... WHERE next_run_utc = ?`) preventing duplicate execution across multiple worker instances or restart cycles.
- **Secrets Protection**: `.env`, `credentials.json`, and `token.json` are strictly excluded from version control in `.gitignore`.
- **Browser Authentication**: Google ID tokens are verified by the backend against the configured Web OAuth client and owner email. Short-lived backend JWTs are held in browser memory only.
- **Service Authentication**: The agent API rejects requests without the backend-only `AGENT_SERVICE_TOKEN`; it must not be exposed as a public browser API.
- **Owner Isolation**: Each MongoDB query for a user's conversations, messages, executions, and approvals is scoped to the authenticated user ID.
- **Durable Chat Actions**: Chat messages, execution status, and pending confirmations are stored in MongoDB; chat requests require an idempotency key.


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

The shared token requests Gmail, Contacts, Calendar, Tasks, Google Drive, and
Google Photos Picker scopes.

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

### Independent service deployment

The web application has three separately deployable processes. Configure the
three environment files from their examples; do not overwrite existing local
`.env` files. MongoDB Atlas or another MongoDB deployment should use TLS and
network access restricted to the backend. Generate separate high-entropy
values for `SESSION_JWT_SECRET` and `AGENT_SERVICE_TOKEN`, and copy only the
agent token into `agent/.env`.

```powershell
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
if (-not (Test-Path frontend\.env)) { Copy-Item frontend\.env.example frontend\.env }
```

Set the Google OAuth Web client ID and allowed owner email in both the frontend
and backend configuration. Add the frontend's deployed origin to the Google
OAuth client's authorized JavaScript origins and to `FRONTEND_ORIGINS`. The
Google Sign-In client ID is public; the OAuth client secret must never be put in
the frontend.

Install and start the central backend:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8001
```

Start the private agent service separately (with its configured agent
environment and the same backend-only service token):

```powershell
.\agent\.venv\Scripts\python.exe -m uvicorn agent.api:app --host 0.0.0.0 --port 8000
```

The agent's network ingress should allow only the central backend. In
production, use HTTPS at the public frontend/backend boundary and configure
`AGENT_SERVICE_URL` to the private agent address. For local development, Vite
proxies `/api` to the central backend on port 8001.

Start the frontend:

```powershell
Push-Location frontend
npm install
npm run dev
Pop-Location
```

The legacy Express gateway in `backend/src` is not part of this deployment
path. The FastAPI service in `backend/app` is the public API. The private agent
also receives a separate, least-privilege MongoDB credential for workflow
collections; it must not receive the backend's identity/chat credential.

### Persistence and migration notes

MongoDB is the source of truth for user identity, chat history, chat executions,
chat confirmations, workflow definitions, workflow executions, and workflow
approvals. The agent uses a separate MongoDB credential for only the workflow
collections; do not give it the backend's broader database credential.
Reminder schedules remain SQLite-backed in `agent/reminders.db`; keep that file
on persistent storage.

Stop the previous agent API and workflow scheduler before the one-time import.
Run the importer against the existing SQLite file before starting either
process with `WORKFLOW_STORAGE=mongodb`:

```powershell
.\agent\.venv\Scripts\python.exe -m agent.services.migrate_workflows_to_mongodb `
  --sqlite-path agent\workflows.db
```

The importer reads SQLite in query-only mode, refuses a non-empty target with
no migration marker, uses insert-only upserts, and retains the original SQLite
file as a backup. It can safely resume an interrupted import from the same
source. Agent startup refuses MongoDB workflow mode until the import-complete
marker is present; once it is enabled, workflow APIs, the engine, and scheduler
all use MongoDB rather than silently falling back to SQLite.

---

## Google Drive and Google Photos

### Google Cloud setup and OAuth scopes

Enable **Google Drive API** and **Google Photos Picker API** in the same Google
Cloud project as the existing OAuth client. Keep the existing OAuth client;
the app uses the shared `agent/credentials.json` and `agent/token.json`.
Reauthorize with `python -m agent.auth.gmail_auth` after enabling the APIs.
An existing token without the new scopes will fail with an actionable
reauthorization message; enabling an API alone does not grant OAuth access.

The Picker uses the required
`https://www.googleapis.com/auth/photospicker.mediaitems.readonly` scope.
Full Drive management uses `https://www.googleapis.com/auth/drive`: the
narrower `drive.file` scope would not let this app browse and manage arbitrary
files that already exist in the user's Drive. Google classifies full Drive
access as a restricted scope, so deployments must satisfy applicable Google
verification and data-use requirements.

### Using the feature

In Chat, open **Google Drive & Photos** to browse folders, search, filter by
MIME type, page through results, and select multiple files. **Add selected to
chat** imports extractable text from text files, PDFs, Google Docs, Sheets,
and Slides. The agent receives the extracted text as untrusted document data.
Scanned PDFs do not receive OCR. Extracted text is capped at 100,000
characters per file; files above the byte limit are not read.

Use **Upload to Drive** to upload one or more device files into the current
folder (or Drive root). Uploads preserve the original bytes and use resumable
Drive API requests. The default per-file cap is 25 MiB and can be changed with
`DRIVE_MAX_UPLOAD_BYTES`. The server reports completion only after Drive
returns a created file ID. Retries with the same operation ID are deduplicated.

Create folders from the browser, navigate nested folders, and use the selected
item actions to rename, move, copy, or move items to Drive trash. Rename, move,
and trash require confirmation; duplicate folder paths are rejected as
ambiguous instead of selecting an arbitrary match. A folder path can be
resolved with `GET /api/drive/folders/resolve?path=College/Projects`.

**Choose from Photos** opens Google's Picker in a separate tab. Select the
media there; once the session reports a completed selection, this page lists
the selected items and can save up to 20 at a time to the current Drive folder.
Picker sessions expire, and media download URLs are kept server-side and are
not returned to the browser. Photos Picker does not support unrestricted
Google Photos library browsing.

### Supported formats and limitations

- Drive upload accepts files with an identified or browser-provided MIME type;
  it does not convert or rewrite their bytes.
- Chat extraction supports text files, CSV/JSON/RTF, PDF, Google Docs, Sheets
  (CSV export), and Slides (PDF export). Other binary files can be opened with
  their real Drive link but are not analyzed by this text-only agent.
- Photos and videos selected from Picker can be saved to Drive. The current
  Groq chat model is text-only, so this implementation does not claim image or
  video understanding.
- Google API access still uses one server-side OAuth token for the configured
  owner account. Google Sign-In authenticates that owner to the web app; it
  does not provide separate Google API credentials per user.

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

- **Confirmation gate**: Sensitive Drive rename, move, and trash actions first return a preview. The CLI and web chat authorize only the exact pending action after a separate confirmation; model-supplied confirmation arguments alone cannot authorize it. This is not web user authentication.
- **Never Permanently Deletes**: The agent uses `trash()`, never permanent `delete()`. Trashed emails can be recovered within 30 days from Gmail Trash.
- **Recipient Validation**: Recipient addresses are strictly validated for standard format. The agent will never guess or invent an address.
- **Prompt Injection Defense**: Email bodies, Drive files, and imported attachments are treated as untrusted data. Instructions inside them cannot execute tools, disclose secrets, or alter system behavior.
- **Secrets Protection**: `.env`, `credentials.json`, and `token.json` are strictly excluded from version control in `.gitignore`.
- **Credential exposure**: If an OAuth client secret or token was exposed, manually revoke the exposed OAuth grant and rotate the OAuth client secret in Google Cloud Console, replace the local credentials file, and reauthorize. This project does not rotate or revoke credentials automatically.

## Known limitations

- Workflow and reminder persistence remains in SQLite; mount durable storage
  for these agent databases. See the migration note above.
- Reminder delivery requires the separate worker process. The default
  notification channel is Telegram; Console delivery is available for local
  development. Claims prevent concurrent workers from processing the same
  reminder, but delivery is at-least-once: a worker or network failure after
  remote delivery but before the database is updated may cause a retry.
- Live Google integrations were not run as part of the default test suite.
- Google Drive full access is required to browse and manage arbitrary existing
  files. Google classifies this as a restricted OAuth scope, and Google Cloud
  verification may be required for wider distribution.
