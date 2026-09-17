# Ready2Rent — Autopilot Build Brief

## How to use this
Save this as `CLAUDE.md` in the project folder root so it loads every session. This project is built and run **entirely on my local machine**. Nothing is deployed or pushed anywhere unless I explicitly approve it later.

## Operating mode
Build this project mostly autonomously, in milestones. After each milestone: explain the changes, then give me exact instructions to run and verify them locally, then continue on your own. **But stop and ask for my explicit approval before any "Approval gate" below** — do not guess or proceed on those. For everything else (routine code, running tests, local dev commands), proceed without pausing, but keep me briefly informed.

## Approval gates — always pause and wait for my "yes"
1. **Tech stack / dependencies** — confirm the stack, and ask before adding any new library.
2. **Database schema** — present the models (from `docs/schema.md`) and wait for sign-off before writing migrations.
3. **Auth & access-control model** — before implementing.
4. **Secrets / external accounts** — anything needing API keys or `.env` values. Never hardcode secrets; ask me to provide them.
5. **Destructive actions** — dropping tables, resetting the database, or deleting files.
6. **Deviations** — any change that departs from this brief.

## Build local, deploy later
- During development everything runs on my machine: Django dev server, React dev server, Postgres + Redis in local Docker containers.
- **Build it deploy-ready:** env-based config (no hardcoded URLs or secrets), CORS configured, frontend and backend cleanly separated. I'll host it after it's done.
- **Do not initialize Git, create commits, configure remotes, or push** during development. Once the whole app is complete and verified, I'll initialize Git and upload the final version myself.
- **Create a `.gitignore` now** excluding secrets, dependencies, and uploads (`.env`, `venv/`, `node_modules/`, `__pycache__/`, media) for that eventual upload.
- **Deploy target (later):** React frontend → Vercel or Netlify; Django backend + Postgres + Redis → a backend host (e.g. Render, Railway, or Fly). Note: Vercel/Netlify host the frontend only, not the Django/Postgres/Redis backend.
- Production deploy is a deferred milestone — do not start it until I approve.

## Keep the frontend verifiable at all times
- The app must be runnable after every milestone. Never leave it broken between milestones.
- Build a thin but working UI early so I can watch it grow.
- After each milestone, give me the exact commands to start backend + frontend, the local URL to open, and what to click to verify.
- If a change will temporarily break the running app, warn me first.

## Product
Ready2Rent helps Calgary homeowners legalize their basement suites. ~Two-thirds of Calgary basement suites aren't up to code; the process is slowed by time, uncertainty, and bureaucracy. A homeowner submits their situation; the company's ops team coordinates permits, contractors, financing guidance, and city paperwork. Two surfaces, one shared backend and database:
1. **Homeowner app** — sign up, complete a multi-step intake (property, existing/planned suite, known code issues, goals), upload documents, track status.
2. **Internal ops app** — staff review a lead queue, assign owners, schedule visits, add notes, and advance each case through its stages.

## Stack (confirm at Gate 1)
- Backend: Python, Django + Django REST Framework
- Database: PostgreSQL, normalized, transactions on multi-step writes
- Caching: Redis (cache the ops lead queue)
- Background jobs: Celery + Redis (notify staff on new leads; email homeowners on status change)
- Frontend: thin React (Vite) client — exists and demos cleanly, not the focus
- Local infra: Postgres + Redis via Docker Compose (run locally)

## Backend emphasis (what matters for the portfolio)
- **Transactions:** wrap multi-step operations atomically so partial failures can't corrupt state.
- **Correctness:** DB-level constraints, validated inputs, well-defined status transitions (no invalid jumps).
- **Access control:** role-based — a homeowner sees only their own data and can never reach staff endpoints.
- **Tests:** cover the data model, transaction behavior, and access rules.

## References to read before designing anything
- `docs/domain-research.md` — real City of Calgary requirements (drives the intake, documents, and compliance items).
- `docs/schema.md` — the database spec (ER diagram in `docs/ready2rent-erd.mermaid`).

## Milestone plan (propose your version at the start, then follow it)
0. Scaffold: project layout, Docker Compose (Postgres + Redis), Django project, a health-check endpoint, and a minimal React app that calls it. → verify locally.
1. Data model + migrations. **[GATE 2]** → verify via Django admin.
2. Auth + roles. **[GATE 3]** → verify login for both roles.
3. Homeowner intake flow + document upload. → verify.
4. Ops queue: list, detail, status transitions (transactional), assignment, visits. → verify.
5. Redis caching on the queue + Celery notifications. → verify.
6. Test suite (model, transactions, access rules). → verify.
7. **DEFERRED — do not start until I approve:** production build config + deploy (frontend → Vercel/Netlify; backend + Postgres + Redis → a backend host like Render/Railway/Fly).

## Discipline
- After each milestone, explain the changes and give run/verify instructions. **Do not use Git during development** (no init, commits, remotes, or push).
- Create a `.gitignore` (secrets, dependencies, uploads) now, ready for the eventual manual upload.
- Keep a `DECISIONS.md` logging key choices and tradeoffs (interview talking points).
- Write a `README.md` covering architecture, the data model, why Celery instead of Kafka at this scale, and how the system would scale.
