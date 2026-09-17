# Deploying Ready2Rent for $0

Ready2Rent runs entirely on free tiers:

| Piece | Host | Plan |
|---|---|---|
| React frontend | Vercel | Hobby (free) |
| Django API | Render | Free web service |
| Redis (cache, rate-limit counters) | Render | Free Key Value |
| PostgreSQL | Supabase | Free |
| Uploaded documents | Supabase Storage (private bucket) | Free |

```
Browser ──► <project>.vercel.app ──(/api/* rewrite)──► ready2rent-api.onrender.com ──► Supabase Postgres (session pooler)
             static React build                         Django + gunicorn             ├► Supabase Storage (S3 API, private)
                                                                                      └► Render Key Value (Redis)
```

The browser only talks to the Vercel origin; Vercel forwards `/api/*` to Render ([`frontend/vercel.json`](../frontend/vercel.json)), so login cookies stay first-party. Documents are never served by URL: the Django views check ownership, read the object with server-only S3 keys, and stream it back.

## Free-tier limitations (verified September 2026)

| Limit | What it means for the demo |
|---|---|
| **Render Free web services sleep after 15 minutes without traffic** and take about **one minute** to wake. | The landing page (Vercel) loads instantly, but the first login or API call after a quiet period waits up to a minute. Vercel waits up to 120 seconds for a proxied request, so it succeeds, just slowly. Open the site a minute before an interview to wake it. |
| **750 free instance hours per workspace per month.** Services suspend when they run out. | One service, even if kept awake all month (~744 h), fits. A second free web service in the same workspace would not. |
| **Render may restart free services at any time.** Free services have **no persistent disk, no Shell, no one-off jobs, no pre-deploy command**, and **cannot send on SMTP ports 25/465/587**. | That is why uploads live in Supabase Storage, migrations run in the start command, the admin account is created from your own computer, and email stays on the console backend. |
| **Render Free Key Value: 25 MB, not persisted, one per workspace.** | Only cache entries and rate-limit counters live there. A restart clears them, which is harmless. |
| **Supabase Free projects pause after 1 week of inactivity.** Two free projects per account. | While paused, the API cannot start (migrations fail at startup) and logins fail. Restore it from the Supabase dashboard; it takes a few minutes. |
| **Supabase Free: 500 MB database, 1 GB file storage, 50 MB max file size, 5 GB egress, no automatic backups.** | Plenty for demo data (the app caps uploads at 20 MB). Nothing is backed up, so don't store anything you need. |
| **Supabase direct database connections are IPv6-only on the free plan.** | Render needs IPv4, so `DATABASE_URL` must be the **session pooler** URI (port 5432, user `postgres.<project-ref>`). Transaction mode (port 6543) is not used because it breaks prepared statements. |
| **Vercel Hobby is for personal, non-commercial use.** | Fine for a portfolio demo. |

## One-time setup

You'll create three accounts (Supabase, Render, Vercel), all free, all signing in with GitHub. None asks for a card for these plans. Never paste secrets into chat, commit them, or put them in `render.yaml`.

### 1. Generate secrets on your computer

In PowerShell:

```powershell
# Database password (letters and digits only, so it needs no URL-encoding)
python -c "import secrets; print(secrets.token_hex(24))"

# Django secret key
python -c "import secrets; print(secrets.token_urlsafe(64))"

# Non-obvious Django admin path
python -c "import secrets; print('staff-' + secrets.token_hex(4) + '/')"
```

Save all three in a password manager.

### 2. Supabase: database and storage

1. Go to supabase.com → **Start your project** → sign in with GitHub.
2. **New project**:
   - Name: `ready2rent`
   - Database password: the one from step 1
   - Region: **West US (Oregon)**, to match Render's Oregon region
   - Under **Security** / Data API options: **turn off "Enable Data API"**. Django talks to Postgres directly, and leaving the Data API on would expose tables over a public REST endpoint. (If you missed it: **Project Settings → Data API → disable**.)
3. Wait for the project to finish provisioning.
4. **Database URL:** click **Connect** at the top → **Connection string** → choose **Session pooler**. Copy the URI, replace `[YOUR-PASSWORD]` with your password, and add `?sslmode=require` to the end. It looks like:
   `postgresql://postgres.abcdefghijklmnop:PASSWORD@aws-0-us-west-2.pooler.supabase.com:5432/postgres?sslmode=require`
5. **Storage bucket:** **Storage** → **New bucket** → name `documents` → leave **Public bucket OFF** → create.
6. **S3 keys:** **Project Settings → Storage → S3 Connection**. Copy the **Endpoint** and **Region**, then **New access key** and copy the **Access key ID** and **Secret access key** (shown once).

### 3. Render: API and Redis

1. Go to render.com → sign up with GitHub → allow access to the `Ready2Rent` repository.
2. **New** → **Blueprint** → select `Ready2Rent`, branch `main`.
3. Render lists **ready2rent-api (Free)** and **ready2rent-redis (Free)**. Fill in the prompts:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | secret key from step 1 |
| `DJANGO_ADMIN_URL` | admin path from step 1 |
| `CSRF_TRUSTED_ORIGINS` | `https://ready2rent.vercel.app` (change later if Vercel gives a different URL) |
| `FRONTEND_URL` | same URL |
| `DATABASE_URL` | session pooler URI from step 2.4 |
| `SUPABASE_S3_ENDPOINT_URL` | S3 endpoint from step 2.6 |
| `SUPABASE_S3_REGION` | region from step 2.6, e.g. `us-west-2` |
| `SUPABASE_S3_ACCESS_KEY_ID` | access key ID |
| `SUPABASE_S3_SECRET_ACCESS_KEY` | secret access key |

4. **Apply**. The first build takes a few minutes. At startup the service runs `python manage.py release` (migrations + expired-token cleanup), then gunicorn.
5. When it shows **Live**, copy its URL from the top of the service page. If it is not exactly `https://ready2rent-api.onrender.com`, the rewrite in `frontend/vercel.json` must be updated to match and pushed.
6. Check it in a browser: `https://ready2rent-api.onrender.com/api/livez/` → `{"status": "ok"}`.

> `sync: false` values are only prompted when the Blueprint is first created. To change one later: service → **Environment** → edit → **Save**, which redeploys.

### 4. Create your admin account (from your computer)

Free services have no Shell, so create the account locally against the Supabase database. The password you type stays on your machine.

```powershell
cd "C:\Users\ASUS ZenBOOK\Ready2Rent\backend"
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = [System.Net.NetworkCredential]::new('', (Read-Host -AsSecureString "Session pooler URI")).Password
python manage.py createsuperuser
Remove-Item Env:DATABASE_URL
```

Paste the session pooler URI when asked (it is hidden as you type). `createsuperuser` then asks for email, name, and password. The account gets the admin role and full Django admin access at `https://ready2rent-api.onrender.com/<DJANGO_ADMIN_URL>`, where you can create staff accounts (role: Staff).

### 5. Vercel: frontend

1. Go to vercel.com → sign up with GitHub → **Add New… → Project** → import `Ready2Rent`.
2. **Project Name:** `ready2rent`. **Root Directory:** `frontend` (click **Edit**). Vercel detects Vite; leave the build settings. No environment variables.
3. **Deploy**, then open the URL Vercel shows.
4. If the URL is not `https://ready2rent.vercel.app`, update `CSRF_TRUSTED_ORIGINS` and `FRONTEND_URL` on Render (**Environment**) to the real URL.

### 6. Smoke test

1. Open the Vercel URL: the landing page appears immediately.
2. **Start application** → register a homeowner. (If the API was asleep, this first request can take up to a minute.)
3. Submit an intake, upload a PDF, then click its file name: it downloads.
4. Log in with the admin account → **Lead queue** shows the lead → claim it → move it to Eligibility check.
5. Render → `ready2rent-api` → **Logs**: the new-lead and status emails are printed there.
6. **System health** (admin) shows database `ok` and redis `ok`.
7. Supabase → **Storage → documents**: the uploaded file is there, in a private bucket.

## Day-to-day

- **Deploy changes:** push to `main`. Render and Vercel both redeploy automatically; migrations run when the new Render instance starts.
- **Before a demo:** open the site a minute early to wake the API. If Supabase paused the project, restore it first (Supabase dashboard → project → **Restore**).
- **Token cleanup** runs on every start. Because free services restart and sleep often, that is frequent enough without a scheduler.
- **Real email later:** set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`. Render Free blocks SMTP ports, so this needs a paid Render instance or an email provider with an HTTP API.
- **Rotating Supabase S3 keys:** create a new key in Supabase, update both S3 variables on Render, then revoke the old key.
