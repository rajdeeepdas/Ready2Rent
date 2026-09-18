# Ready2Rent

Ready2Rent helps Calgary homeowners turn an unpermitted basement suite into a legal, rentable one. A homeowner describes their property once, uploads their documents, and tracks progress while an internal ops team works the case through permits, contractors, and City of Calgary paperwork.

It's one product with two front doors over a single backend and database:

1. **Homeowner app.** Sign up, complete a short intake, upload documents, track status.
2. **Ops app.** Staff work a queue of leads, claim or assign them, schedule visits, leave notes, and move each case through its stages.

This started as a University of Calgary hackathon project and grew into a full stack build, with the weight on the backend: the data model, transactional writes, and role based access.

> **Status:** Milestones 0 through 7 complete. Configured for free-tier hosting (Vercel, Render, Supabase); see [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Trying it

Anyone can create a homeowner account from **Sign up** and submit an application. Staff and admin accounts are created by the site owner in Django admin; there are no public demo credentials or preloaded sample data. The live demo runs on free tiers, so the API may take up to a minute to respond after a period of inactivity (details in [`docs/DEPLOY.md`](docs/DEPLOY.md)).

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite 8 (plain JSX) |
| API | Django 6.1 + Django REST Framework 3.18 |
| Database | PostgreSQL 17 |
| Cache and broker | Redis 8 |
| Background jobs | Celery 5.6 |
| Local infra | Docker Compose (Postgres + Redis) |
| Hosting | Vercel (frontend), Render (API + Redis), Supabase (PostgreSQL + private file storage) |

The frontend and backend are fully separate and configured through environment variables, so each deploys on its own. In production the SPA is on Vercel, the API and Redis are on Render, and PostgreSQL and uploaded files are on Supabase.

```
┌──────────────────┐   HTTPS/JSON    ┌──────────────────────┐
│ React (Vite) SPA │ ─────────────▶ │ Django + DRF API      │
└──────────────────┘                 └──────┬───────┬───────┘
                                   ┌────────▼──┐ ┌──▼────────┐
                                   │ PostgreSQL│ │  Redis    │
                                   └───────────┘ └──┬────────┘
                                            ┌───────▼────────┐
                                            │ Celery worker  │
                                            └────────────────┘
```

## What it does

**Data model.** Users (homeowner, staff, admin), Properties, Suites, Applications, and the records that hang off an application: an append only status history, a compliance checklist, permits, documents, and visits. Every primary key is a UUID. The full specification is in `docs/schema.md`, with an ER diagram in `docs/ready2rent-erd.mermaid`.

**Intake.** When a homeowner submits, one atomic transaction creates the property, suite, and application, seeds the compliance checklist and the required documents, and writes the first history row. The required document set is computed from the suite type and the home's age, following `docs/domain-research.md`.

**Status transitions.** Applications move through an explicit state machine. Each change runs under a row lock (`select_for_update` inside `transaction.atomic()`), and reaching the final stages also requires every needed permit approved and an inspection completed.

**Access control.** Homeowners see only their own data, filtered at the queryset and rechecked on the loaded row, so another homeowner's application reads as a 404. Ops routes require staff or admin, and staff can act only on the applications assigned to them, while assignment itself is admin only. Auth uses a short lived in memory access token plus a rotating `HttpOnly` refresh cookie with CSRF protection.

**Ops queue.** Staff get a filterable, paginated queue with per row document and code item counts, plus a summary of counts by status. The queue is cached in Redis and invalidated on every write, and falls back to the database if Redis is down.

**Notifications.** Celery tasks (queued only after a transaction commits) email staff on new leads and email homeowners on status changes and document reviews. Email uses Django's console backend: locally messages print in the Celery worker's terminal; on the free hosting tier tasks run inside the web process and messages appear in the Render logs.

**Uploads.** PDF, PNG, and JPEG up to a size cap, checked by extension and magic bytes, served only as authenticated downloads. Files are stored on local disk in development and in a private Supabase Storage bucket (via its S3 API) in production.

The data model specification is in `docs/schema.md`; the security review and design decisions are in `DECISIONS.md`.

## Running it locally

You'll need Python 3.14, Node 24, and Docker Desktop.

```powershell
copy .env.example .env          # set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d            # Postgres + Redis

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver      # API at http://localhost:8000

cd ..\frontend
npm install
npm run dev                     # app at http://localhost:5173
```

For notifications, run a Celery worker in another terminal: `celery -A config worker -l info --pool=solo` (drop `--pool=solo` off Windows). Emails print there.

Routes: `/` landing page, `/register` signup, `/login`, `/app` homeowner dashboard, `/ops` staff queue, `/health` system health (staff or admin only).

## Tests

```powershell
cd backend
pytest
```

The suite runs against a temporary Postgres database and an isolated Redis, so Docker must be up. It covers the data model (enums, constraints, indexes, delete behaviour, append only history), transactions (intake, transitions, assignment, and document review are all or nothing, with two real threads racing a locked row), and access rules (a matrix built from the URLconf checks every route against every role).

**534 tests, 97% line coverage** (migrations and tests excluded). To reproduce:

```powershell
pytest --cov
```

## Deployment

Everything runs on free tiers: the frontend on Vercel, the Django API and a Redis cache on Render, and PostgreSQL plus a private document bucket on Supabase. `frontend/vercel.json` forwards `/api/*` to the API so the browser stays on one origin, and sets a strict Content-Security-Policy. `render.yaml` defines the API and Redis; because free Render services have no pre-deploy step or shell, database migrations run from the start command and the admin account is created locally against the Supabase database.

Free tiers have real limits: the API sleeps after 15 idle minutes and takes about a minute to wake, and the Supabase project pauses after a week without activity. The step by step setup and every limit are in [`docs/DEPLOY.md`](docs/DEPLOY.md).

## How it scales

* The API tier is stateless, so Django can run multiple replicas behind a load balancer.
* Indexes back the ops queue, and `select_for_update` keeps concurrent staff actions correct on a single hot row. Read replicas can serve reads when needed.
* Redis caches the queue, which is read far more than it changes.
* Celery workers scale independently of the API.
* File storage goes through Django's storage API. Production already uses S3-compatible object storage, so switching providers is configuration only.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 0 | Scaffold: layout, Docker Compose, health check, React app | Done |
| 1 | Data model and migrations | Done |
| 2 | Auth and roles | Done |
| 3 | Homeowner intake and document upload | Done |
| 4 | Ops queue: detail, transitions, assignment, visits | Done |
| 5 | Redis caching and Celery notifications | Done |
| 6 | Test suite | Done |
| 7 | Production build and deploy | Pending |
