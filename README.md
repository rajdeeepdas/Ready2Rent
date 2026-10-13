# Ready2Rent

Ready2Rent is a full stack case management platform that helps Calgary homeowners organize the process of creating or legalizing a secondary suite. Homeowners submit property details and documents through a guided intake, while operations staff manage each case through eligibility review, permits, construction, inspections, and registration.

The project began as a University of Calgary hackathon concept and evolved into a production configured application focused on secure document handling, reliable workflow transitions, transactional data integrity, and clear separation between homeowner and staff experiences.



## Demo access

Explorers can access both user flows through the deployed application:

| Experience | Email | Password | Access |
| --- | --- | --- | --- |
| Homeowner | `user@ready2rent.com` | `user12345` | Submit and track a secondary suite application |
| Staff dashboard | `admin@ready2rent.com` | `admin123` | Review the operations queue and manage applications |

Application login: [ready2rent.vercel.app/login](https://ready2rent.vercel.app/login)

The staff dashboard account is for the Ready2Rent operations interface. It is not intended for Django administration access.

## Core capabilities

1. Guided homeowner registration and secondary suite intake

2. Property, suite, application, compliance, permit, visit, and document records

3. Private uploads for PDF, PNG, and JPEG documents

4. Homeowner progress tracking with a complete application history

5. Filterable and paginated staff queue with status summaries

6. Case claiming, administrative assignment, internal notes, and visit scheduling

7. Explicit workflow rules for every application status change

8. Permit and inspection requirements before final registration and completion

9. Redis caching with automatic invalidation after application changes

10. Celery notifications for new applications, status updates, and document reviews

11. Role based authorization for homeowners, staff, and administrators

12. Automated tests for access control, transactions, security, storage, caching, and domain rules

## Architecture

![Ready2Rent architecture](docs/diagram.png)

The React single page application provides separate homeowner and operations experiences through one interface. Requests pass through a shared API client to Django REST Framework endpoints. Business rules remain in the service layer, PostgreSQL stores authoritative case data, Redis supports caching and background work, and private file storage protects uploaded documents.


## User workflows

### Homeowner experience

1. Create an account and sign in.

2. Complete the intake with property, suite, ownership, and project details.

3. Submit the application as one atomic operation.

4. Upload required documents and supporting files.

5. Track the current status, requirements, permits, visits, and public history.

6. Withdraw an active application when permitted by the workflow.

### Operations experience

1. Review application counts and a filterable case queue.

2. Open a complete case record with homeowner, property, suite, and document information.

3. Claim an unassigned case or assign it as an administrator.

4. Review documents, update compliance items, manage permits, and schedule visits.

5. Add internal notes and move the application through approved transitions.

6. Complete a case only after its required permit and inspection evidence exists.

## Application lifecycle

```text
Intake
  ↓
Eligibility check
  ↓
Development permit when required
  ↓
Building and trade permits
  ↓
Construction
  ↓
Inspections
  ↓
Registered
  ↓
Complete
```

Eligible active stages can move to `on_hold` and later resume to their recorded prior stage. Applications can also be withdrawn where the state machine permits it. Terminal applications cannot transition again.

## Technology

**Frontend:** React 19.3, React Router 7.18, Vite 8.3, JSX, and custom CSS

**Backend:** Python 3.14, Django 6.1, and Django REST Framework 3.18

**Database:** PostgreSQL 17

**Cache and task broker:** Redis 8

**Background processing:** Celery 5.6

**Authentication:** JSON Web Tokens with Simple JWT, rotating refresh tokens, and token blacklisting

**File storage:** Local private media during development and private Supabase Storage through its S3 compatible API in production

**Deployment:** Vercel for the frontend, Render for the API and Redis, and Supabase for PostgreSQL and file storage

**Testing:** pytest, pytest django, Factory Boy, and pytest cov

## Data model

The central `Application` connects a homeowner, a property, a suite, and an assigned staff member. Related records capture compliance items, permits, uploaded documents, scheduled visits, and append only status history.

UUID primary keys are used throughout the domain model. Database constraints and indexes enforce important invariants and support queue performance. The complete schema is documented in [`docs/schema.md`](docs/schema.md), with the entity relationship diagram in [`docs/ready2rent-erd.mermaid`](docs/ready2rent-erd.mermaid).

## Security and reliability

1. Homeowner querysets are restricted to records owned by the authenticated user, followed by an independent object permission check.

2. Staff members can modify only applications assigned to them. Administrators control assignment and reassignment.

3. Access tokens remain in browser memory. Rotating refresh tokens use an `HttpOnly` cookie and CSRF protection.

4. Authentication, intake, and upload endpoints use Redis backed throttling.

5. Uploaded files are validated by extension, size, and magic bytes, then served only through authenticated download endpoints.

6. Multi record operations use database transactions. Status transitions also lock the application row to prevent concurrent updates from corrupting history.

7. Queue cache failures fall back to PostgreSQL so Redis availability does not block case work.

8. Notifications are queued only after a successful database commit.

9. Production settings enforce secure cookies, transport security options, explicit hosts and origins, strict response headers, and a configurable administration path.

10. Authenticated API responses use private cache controls to prevent shared proxy storage.



## Project structure

```text
Ready2Rent
├── backend
│   ├── accounts          Authentication, users, roles, and permissions
│   ├── applications      Domain models, APIs, services, workflow, cache, and tasks
│   ├── config            Django settings, Celery, storage, and root routing
│   ├── core              Shared models, middleware, health checks, and release command
│   └── tests             Backend test suite
├── docs
│   ├── diagram.png        Deployed Diagram
│   ├── domain-research.md Calgary secondary suite research
│   ├── schema.md         Data model and access rules
│   └── ready2rent-erd.mermaid  Initial System Design
├── frontend
│   ├── public            Brand assets
│   └── src               React application, pages, components, auth, and API client
├── docker-compose.yml    Local PostgreSQL and Redis services
├── render.yaml           Render service definition
└── README.md
```

## Local development

### Requirements

Install Python 3.14, Node.js 24, and Docker Desktop before continuing.

### 1. Clone the repository

```bash
git clone https://github.com/rajdeeepdas/ready2rent.git
cd ready2rent
```

### 2. Configure the environment

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux:

```bash
cp .env.example .env
```

Open `.env`, replace `DJANGO_SECRET_KEY`, and replace `POSTGRES_PASSWORD`. A secure Django key can be generated with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 3. Start PostgreSQL and Redis

```bash
docker compose up -d
```

### 4. Start the backend

On Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`. The API runs at `http://localhost:8000`.

### 5. Start the frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 6. Start notifications when needed

Open a third terminal, activate the backend virtual environment, and run:

```bash
cd backend
celery -A config worker -l info --pool=solo
```

The `solo` pool is required on Windows. On macOS or Linux, omit that option. With the default console email backend, notification content appears in the worker terminal.


Public registration always creates a homeowner. Administrators can create staff users and set roles through Django administration.

## Main application routes

**Health endpoints:** `/api/livez/` is public and minimal, while `/api/health/` is restricted to staff and administrators.

## Testing

Ensure the local PostgreSQL and Redis services are running, then execute:

```bash
cd backend
pytest
```

Generate a coverage report with:

```bash
pytest --cov
```

The current suite contains 534 automated tests and reports 97 percent line coverage, excluding migrations, tests, and server entry points. Coverage includes authentication, authorization, database constraints, workflow transitions, concurrent updates, document security, cache behavior, notifications, storage backends, deployment readiness, and API access rules.

## Deployment

The repository includes production configuration for a zero cost demonstration environment:

1. Vercel builds and serves the React application.

2. Render runs Django through Gunicorn and provides Redis.

3. Supabase provides PostgreSQL and a private document bucket.

4. Frontend rewrites keep browser API requests on the same origin.

5. The release command applies migrations and removes expired refresh tokens before the web server starts.


## Product scope

Ready2Rent organizes information and operational work. It does not replace official City of Calgary requirements, legal advice, engineering review, permit approval, inspection, or qualified construction services. Requirements can change, so production use should always verify current municipal guidance.

## Documentation


1. [`docs/schema.md`](docs/schema.md) defines the data model, permissions, workflow, and transaction boundaries.

2. [`docs/domain-research.md`](docs/domain-research.md) records the domain research used to shape intake and document requirements.

3. [`docs/ready2rent-erd.mermaid`](docs/ready2rent-erd.mermaid) contains the entity relationship diagram source.


## License

No open source license is currently included. Standard copyright restrictions therefore apply.
