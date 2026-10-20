# Render + Vercel Deployment

The production layout uses a Vercel static frontend, a public Render backend,
a private Render agent service, a Render scheduler worker, and MongoDB Atlas:

```text
Browser -> Vercel frontend -> Render backend -> private Render agent
                                      |                 |
                                      +--- MongoDB Atlas-+
                                                        +-- scheduler worker
```

The backend is the only public API. Never put MongoDB credentials,
`GROQ_API_KEY`, Google OAuth files, `AGENT_SERVICE_TOKEN`, or
`SESSION_JWT_SECRET` in Vercel or a `VITE_*` variable. The Google Web client ID
is public and is required by the browser.

## Before deploying

1. Create a MongoDB Atlas database. Allow network access from Render using the
   current Render outbound IP ranges or your chosen network policy; do not use
   an unrestricted database user.
2. In Google Cloud Console, create a **Web application** OAuth client for
   Google Identity Services. Add the Vercel production and preview origins that
   you will use as authorized JavaScript origins. Use the Web client ID for
   both `GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID`.
3. Create or select a Google **Desktop app** OAuth client for the agent's Gmail,
   Contacts, Calendar, Tasks, Drive, and Photos scopes. Enable the corresponding
   Google APIs, authorize the owner account locally, and prepare its
   `credentials.json` and `token.json`. Keep both files private. Configure the
   OAuth consent screen and any required Google verification before relying on
   production users.
4. Generate two separate random values of at least 32 characters for
   `AGENT_SERVICE_TOKEN` and `SESSION_JWT_SECRET`. Generate them locally with
   `node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"`;
   do not paste secrets into source files or commit them.

## Render

Create all three Render services from the repository with the repository root
as the **Root Directory**. Use Python 3.12 or newer, and set each build command
and start command below. The private service and persistent disks require a
Render plan that supports them.

### Agent private service

Create a **Private Service** with:

```text
Build:  pip install -r agent/requirements.txt
Start:  mkdir -p /var/data && if [ ! -f /var/data/token.json ]; then cp /etc/secrets/token.json /var/data/token.json; fi && python -m uvicorn agent.api:app --host 0.0.0.0 --port $PORT
```

Attach a persistent disk mounted at `/var/data`. Add Render Secret Files named
`credentials.json` and `token.json`, containing the files authorized for the
agent. Set these environment variables:

```text
GROQ_API_KEY=<Groq API key>
GROQ_MODEL=llama-3.3-70b-versatile
AGENT_SERVICE_TOKEN=<same random value used by backend>
GOOGLE_CREDENTIALS_FILE=/etc/secrets/credentials.json
GOOGLE_TOKEN_FILE=/var/data/token.json
WORKFLOW_STORAGE=mongodb
WORKFLOW_MONGODB_URL=<MongoDB Atlas connection string>
DATABASE_NAME=personal_agent
USER_TIMEZONE=<your IANA timezone>
```

Keep this service private. The backend's `AGENT_SERVICE_URL` must use its
Render **internal** address, not its public URL. A token file is copied to the
persistent disk only on first start so refreshes survive redeploys.

### Scheduler background worker

Create a **Background Worker** from the same repository:

```text
Build:  pip install -r agent/requirements.txt
Start:  mkdir -p /var/data && if [ ! -f /var/data/token.json ]; then cp /etc/secrets/token.json /var/data/token.json; fi && python -m agent.services.workflow_scheduler
```

Give it the same agent environment variables, `credentials.json` and `token.json`
Secret Files, and a persistent disk mounted at `/var/data`. Use the same
`WORKFLOW_MONGODB_URL`, `DATABASE_NAME`, and `AGENT_SERVICE_TOKEN` as the agent.
The worker needs the Google token because scheduled workflows call Google APIs.

Before enabling MongoDB workflow storage, run the migration once from a Render
Shell or trusted one-off worker with the same agent environment. If there is no
existing workflow database, initialize an empty source first:

```text
python -c "from agent.services.workflow_service import init_workflow_db; init_workflow_db('/var/data/workflows.db')"
python -m agent.services.migrate_workflows_to_mongodb --sqlite-path /var/data/workflows.db
```

If you have existing workflows, place the existing `agent/workflows.db` on the
persistent disk and pass its path to the migration command instead. Do not start
the agent or scheduler against MongoDB until migration completes; startup
intentionally fails closed without the migration marker.

### Public backend web service

Create a **Web Service** from the same repository:

```text
Build:  pip install -r backend/requirements.txt
Start:  python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
```

Set:

```text
MONGODB_URL=<MongoDB Atlas connection string>
DATABASE_NAME=personal_agent
AGENT_SERVICE_URL=http://<agent-internal-host>:<agent-port>
AGENT_SERVICE_TOKEN=<same random value used by agent>
GOOGLE_CLIENT_ID=<Google Web client ID>
ALLOWED_GOOGLE_EMAIL=<one authorized owner email>
SESSION_JWT_SECRET=<separate random value, at least 32 characters>
SESSION_TTL_SECONDS=3600
FRONTEND_ORIGINS=https://<your-production-domain>,https://<your-preview-domain>
MAX_REQUEST_BODY_BYTES=31457280
```

Use the private service's internal hostname and port shown by Render for
`AGENT_SERVICE_URL`. Do not use `*` for `FRONTEND_ORIGINS`; list the exact
HTTPS origins that will call the API. The health endpoint
`https://<backend>.onrender.com/api/health` should return 200. Readiness at
`/api/ready` should return 200 after MongoDB and the private agent are reachable.

## Vercel

1. Import the same repository into Vercel and set **Root Directory** to
   `frontend`.
2. Use the Vite defaults, or specify build command `npm run build` and output
   directory `dist`.
3. Set `VITE_API_BASE_URL` for Production and any Preview environment you
   intend to use:

   ```text
   VITE_API_BASE_URL=https://<backend>.onrender.com
   ```

   The frontend loads the public Google Web client ID from the backend's
   `/api/config` endpoint, so set `GOOGLE_CLIENT_ID` once on Render rather than
   duplicating it in Vercel or on each device.
4. Add each actual Vercel production/preview origin to both Google OAuth's
   authorized JavaScript origins and the backend's comma-separated
   `FRONTEND_ORIGINS`. Redeploy Vercel after changing `VITE_API_BASE_URL`.

`VITE_API_BASE_URL` is a public build setting. Never add any backend or agent
secret to Vercel. The app keeps its short-lived user session in memory and
sends it to the backend as a bearer token.

## Local development and reported errors

The backend error in the terminal is caused by empty or placeholder values in
`backend/.env`; the backend correctly refuses to start without them. Configure
the Google Web client ID once as `GOOGLE_CLIENT_ID` in `backend/.env`; the UI
loads it from the backend. These values cannot be generated by the app: fill
them using your MongoDB and Google Cloud accounts. Local `.env` files are
ignored by Git.

Create any missing local files without overwriting existing ones:

```powershell
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
if (-not (Test-Path agent\.env)) { Copy-Item agent\.env.example agent\.env }
if (-not (Test-Path frontend\.env)) { Copy-Item frontend\.env.example frontend\.env }
```

Set the six backend required values (`MONGODB_URL`, `AGENT_SERVICE_URL`,
`AGENT_SERVICE_TOKEN`, `GOOGLE_CLIENT_ID`, `ALLOWED_GOOGLE_EMAIL`, and
`SESSION_JWT_SECRET`). The backend's `GOOGLE_CLIENT_ID` is shared with the UI
through `/api/config`; no frontend Google ID setting is needed. Set the same
`AGENT_SERVICE_TOKEN` in `agent/.env` and set `GROQ_API_KEY` in `agent/.env`.
Use a MongoDB URL for the backend. The agent can use its
default local SQLite workflow store; only set `WORKFLOW_STORAGE=mongodb` when
you have completed the workflow migration.

For a hosted deployment, upload your authorized `agent/token.json` to the
Render agent service as the initial token Secret File and configure the
persistent token path described above. Gmail API calls then use that one
server-side authorization for all signed-in devices. Users still sign in to
the web app separately on each device with the allowed Google account.

For local Google Sign-In, authorize the exact origin printed by Vite in Google
Cloud Console. The `Port 5173 is in use` message means another process owns that
port; Vite can still start on `5174`, so open the URL it prints. Stop the
existing development server if you want to restore port 5173.

Then run from the repository root in PowerShell:

```powershell
npm install
npm run dev
```

The root script starts the agent at `127.0.0.1:8000`, backend at
`127.0.0.1:8001`, frontend at `127.0.0.1:5173` (or the next free port), and
the scheduler. For local backend settings use
`AGENT_SERVICE_URL=http://127.0.0.1:8000` and
`FRONTEND_ORIGINS=http://127.0.0.1:5173` (include the actual Vite origin if
calling the backend directly rather than through the Vite proxy).

Run `npm run verify` for frontend lint/build and the Python test suite.