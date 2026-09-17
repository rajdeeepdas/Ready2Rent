# Deploying Ready2Rent

Frontend on **Vercel** (free), backend on **Render**: a Django web service with a persistent disk, PostgreSQL, and Redis (Key Value), all defined in [`render.yaml`](../render.yaml). Both hosts deploy from the GitHub repo and redeploy on every push to `main`.

```
Browser ──► ready2rent.vercel.app ──(/api/* rewrite)──► ready2rent-api.onrender.com ──► Postgres
             static React build                          Django + gunicorn + disk      └► Redis
```

The browser only ever talks to the Vercel origin, so login cookies stay first-party. Vercel forwards `/api/*` to Render (see [`frontend/vercel.json`](../frontend/vercel.json)).

## Cost

Prices are set by the hosts and shown before you confirm anything. As configured:

| Resource | Plan |
|---|---|
| Vercel project | Hobby (free) |
| Render web service `ready2rent-api` | Starter (always on) |
| Render disk (uploads) | 1 GB |
| Render PostgreSQL `ready2rent-db` | Basic 256 MB |
| Render Key Value `ready2rent-redis` | Free |

Notification tasks run inside the web process (`CELERY_TASK_ALWAYS_EAGER=true`), so there is no separate worker to pay for. Emails use Django's console backend and appear in the Render service logs. To add a dedicated Celery worker later, see the commented block in `render.yaml`.

## Launch checklist

Do these in order. Never paste secrets into chat, commit them, or put them in `render.yaml`.

### 1. Generate your secrets locally

```powershell
# Django secret key (50+ random characters)
python -c "import secrets; print(secrets.token_urlsafe(64))"

# A non-obvious admin path
python -c "import secrets; print('staff-' + secrets.token_hex(4) + '/')"
```

Keep both in a password manager. You'll paste them into Render in step 3.

### 2. Render account and payment

1. Sign up at render.com with GitHub and allow access to the `Ready2Rent` repository.
2. **Add a payment method in the Render dashboard** (Account settings → Billing). The Starter web service, disk, and Basic Postgres are paid.

### 3. Create the backend from the Blueprint

1. Render dashboard → **New** → **Blueprint** → select the `Ready2Rent` repo, branch `main`.
2. Render reads `render.yaml` and lists the web service, database, and Key Value instance with their prices. Review them.
3. Fill in the prompted values:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | the key from step 1 |
| `DJANGO_ADMIN_URL` | the admin path from step 1 |
| `CSRF_TRUSTED_ORIGINS` | `https://ready2rent.vercel.app` (your exact Vercel URL, no trailing slash) |
| `FRONTEND_URL` | the same Vercel URL |

4. Click **Apply**. The first deploy installs dependencies, collects static files, runs migrations, and starts gunicorn.
5. When the service shows **Live**, note its URL. If it is not exactly `https://ready2rent-api.onrender.com` (the name was taken), update the rewrite destination in `frontend/vercel.json`, commit, and push.
6. Check it:

```powershell
curl https://ready2rent-api.onrender.com/api/livez/
```

Expected: `{"status": "ok"}`

### 4. Create your admin account

Render dashboard → `ready2rent-api` → **Shell**:

```bash
python manage.py createsuperuser
```

Admin-role accounts get full Django admin access at `https://ready2rent-api.onrender.com/<your DJANGO_ADMIN_URL>`. Create staff accounts there (role: Staff).

### 5. Frontend on Vercel

1. Sign up at vercel.com with GitHub.
2. **Add New** → **Project** → import `Ready2Rent`.
3. Set **Project Name** to `ready2rent` and **Root Directory** to `frontend`. Vercel detects Vite; leave build settings as they are. No environment variables are needed.
4. **Deploy**. If `ready2rent.vercel.app` was taken, use the URL Vercel assigned, then go back to Render and update `CSRF_TRUSTED_ORIGINS` and `FRONTEND_URL` to match (Render redeploys automatically).

### 6. Smoke test the live site

1. Open the Vercel URL. The landing page loads.
2. **Start application** → register a homeowner → submit an intake → upload a PDF. The document shows as Uploaded.
3. Log in as your admin account → `/ops` shows the lead → claim it and move it to Eligibility check.
4. Render → `ready2rent-api` → **Logs**: the new-lead and status-update emails are printed there.
5. Log in as admin → **System health** shows database `ok` and redis `ok`.
6. Redeploy once (Render → Manual Deploy) and confirm the uploaded document still downloads, which proves the disk persists.

## Operating notes

- **Redeploys:** push to `main`. Render runs `migrate` and a refresh-token cleanup before each deploy.
- **Uploads** live on the Render disk at `/var/data/media`. A service with a disk runs as a single instance and has a few seconds of downtime per deploy.
- **Swapping in real email later:** set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` on the Render service. No code changes.
- **Throttling behind the proxy:** `DJANGO_NUM_PROXIES=0` keys rate limits on the full forwarded-for chain, so visitors never share a bucket. The trade-off is that a determined attacker can vary that header to dodge per-IP limits (see `DECISIONS.md` M7-5).
