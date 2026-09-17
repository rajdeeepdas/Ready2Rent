# Decisions log

Key choices and the tradeoffs behind them, in chronological order. Each entry is meant to be a self-contained talking point.

---

## M0-1. Django 6.1 instead of the 5.2 LTS line

**Context.** The development machine runs Python 3.14. Django 5.2 LTS targets Python 3.10 to 3.13; Python 3.14 support in that line is a late patch addition and the Celery/psycopg stack resolves cleanly only against current releases.

**Decision.** Pin Django 6.1.1 (current stable) with djangorestframework 3.18.1, psycopg 3.3.5, celery 5.6.3. Every pin was resolved by pip against Python 3.14 before being approved.

**Tradeoff.** 6.1 has a shorter support window than an LTS. For a portfolio project that will be maintained actively this is fine; a company project would either pin the LTS with Python 3.13 or plan the 6.2 LTS upgrade (April 2027).

## M0-2. PostgreSQL only, no SQLite fallback

**Decision.** `settings.py` has no SQLite path. Development and tests run against the same Postgres engine that production will use.

**Why.** The project's value is in DB-level correctness: unique constraints with conditions, `select_for_update()` row locks, transactional multi-row writes. SQLite silently ignores or emulates several of these, so a SQLite dev path would hide exactly the bugs this project exists to prevent.

## M0-3. One `.env` at the repo root, shared by Docker Compose and Django

**Decision.** Docker Compose reads `.env` from its own directory automatically; Django's settings look for the same file one level above `backend/`. Both therefore see one `POSTGRES_PASSWORD`, so the container and the app can never drift.

**Deploy-readiness.** In production there is no `.env` file. The host injects variables, and `DATABASE_URL` (provided by Render/Railway/Fly) takes precedence over the individual `POSTGRES_*` values. The frontend has its own `frontend/.env` with just `VITE_API_BASE_URL`, because Vite only exposes `VITE_`-prefixed variables and the SPA is deployed separately.

## M0-4. Health check reports each dependency and returns 503 when degraded

**Decision.** `GET /api/health/` runs `SELECT 1` against Postgres and `PING` against Redis, and returns `{"status": "ok" | "degraded", "checks": {...}}` with HTTP 200 or 503.

**Why.** Humans and dashboards use the body to see which dependency is down. Making the default permission `IsAuthenticated` means any endpoint added later is private unless someone deliberately opens it.

**Revised after Milestone 5 (see M5-11).** The detailed report is no longer public.

## M5-11. Detailed health is staff-only; a separate minimal liveness probe is public

**Decision.** `/api/health/` (Django version, dependency status, timestamp) now requires the staff or admin role through the same `IsOps` permission used by the ops surface: anonymous callers get 401 and homeowners 403, exactly like every other protected endpoint. A new `/api/livez/` returns only `{"status": "ok"}` with no authentication, for hosting-platform and container probes. In the SPA the health page sits behind the staff/admin route guard and is linked only from the ops navigation.

**Why.** Framework version and infrastructure topology are reconnaissance material; they should not be readable by anyone who finds the URL. Probes only need to know the process answers, so the public endpoint reveals nothing else. Reusing the existing role permission rather than a special case keeps one access-control mechanism to audit.

---

## M6-1. Tests were written with each milestone; Milestone 6 is an audit, not a start

**Decision.** Every milestone shipped its own tests, so the suite already covered the model, transactions, and access rules when Milestone 6 began. This milestone audited the three areas the brief names against the modules that exist, filled the gaps, and documented the map (README, "What the suite covers").

**Why.** Tests written alongside the code catch mistakes when they are cheap; a test milestone at the end would have meant rediscovering bugs that were already shipped. What a final pass is good for is the cross-cutting checks nobody writes per feature: an access matrix over every route, admin pages for every model, and the pure helpers that were only exercised indirectly.

## M6-2. The access matrix is generated from the URLconf, not written by hand

**Decision.** `test_access_matrix.py` walks Django's resolver, collects every named route under `/api/`, and asserts the role outcome for each: anonymous 401 on all protected routes, homeowner 403 on all ops routes, staff and admin 403 on all homeowner routes. A route that is neither public, any-authenticated, nor on a surface fails a classification test.

**Why.** The most likely future access bug is a new endpoint that forgets a permission class. A hand-written list would not include it; a generated one cannot miss it. DRF runs authentication and permissions before method dispatch, so a GET proves the gate even on POST-only routes.

## M6-3. Finding: an admin-role user is not automatically a Django superuser (resolved in M7-3)

**Observation.** `role=admin` grants Django admin *login* (`is_staff` is derived from role), but model pages inside the admin still need Django permissions: `createsuperuser` accounts have them (superuser flag), an admin-role account created through the admin UI does not, and sees an empty admin. A test documents this behaviour rather than hiding it.

**Options, not yet decided.** (a) Derive `is_superuser` from `role == admin` on save, making the role the single source of truth; (b) keep Django permissions separate so a future "admin" role could be narrower than superuser; (c) grant a fixed permission group on role change. (a) is simplest and matches the spec's "admin: any". This is a Gate 6 deviation question for the owner; until decided, create admin accounts with `createsuperuser` or tick "superuser status" in the admin.

## M7-1. Pre-launch security review

Every finding below was fixed and has a regression test in `tests/test_security.py`.

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | **Login CSRF.** Login and register accepted form posts without a CSRF check. A hostile page could auto-submit a form that signs the victim into an attacker-owned account, so the victim's land title and photos would be uploaded where the attacker can read them. | High | Login, register, refresh, and logout accept JSON only (a cross-site form cannot send it) and run Django's CSRF token + Origin check. The SPA sends the token. |
| 2 | **Oversized JSON bodies.** `DATA_UPLOAD_MAX_MEMORY_SIZE` had been raised to 21 MB for every request, so any endpoint would buffer a 21 MB JSON body in memory. | Medium | Restored Django's 2.5 MB default. File uploads stream to disk and are unaffected. |
| 3 | **Unbounded writes.** A single homeowner could submit unlimited intakes (each emails every staff member) and unlimited extra documents (disk exhaustion). | Medium | Per-user throttles: 10 intakes/day, 60 uploads/hour. At most 25 extra documents per application, checked under a row lock. |
| 4 | **Email header injection.** Street addresses typed by homeowners go into email subjects; a line break would break or alter headers. | Low | Subjects collapse whitespace and cap length. Bodies were already plain text. |
| 5 | **500 on bad input.** A non-UUID `assigned` queue filter raised an unhandled error. | Low | Validated; returns 400. |
| 6 | **Production boot with a weak key.** Nothing stopped a deploy with the placeholder `SECRET_KEY`, which would make JWTs forgeable. | High if hit | `DEBUG=false` refuses to start unless the key is 50+ random characters. |
| 7 | **Missing production transport settings.** | Medium | HTTPS redirect (liveness probe exempt), HSTS, secure session cookie, explicit framing/referrer/COOP headers, admin path from env. |

**Checked and already sound:** SQL injection (ORM only, parameters allow-listed), XSS (JSON API, React escaping), IDOR (queryset + object checks, UUIDs, generated access matrix), path traversal on upload filenames, uploaded files never served publicly, timing-safe login (Django's backend hashes for unknown users too), no hardcoded secrets in source, `npm audit` clean.

**Prompt injection** does not apply: the application makes no AI or LLM calls. If an AI feature is ever added, homeowner-entered text (descriptions, notes, filenames) must be treated as untrusted model input.

**Known residual risks, accepted for now:**
- Registration reveals whether an email already has an account. Closing this needs email verification (deferred, needs an email provider under Gate 4). Throttling limits bulk probing.
- Upload checks prove file type, not that a file is benign. Antivirus scanning is a post-launch option.
- Per-IP throttles slow but do not stop distributed credential stuffing (see M2-6).
- The frontend host must send a Content-Security-Policy and framing headers; that config depends on the host chosen at launch.

## M6-4. Coverage measurement deferred pending Gate 1 (resolved in M7-4)

A line-coverage report needs `pytest-cov` (and its dependency `coverage`), which was not on the approved dependency list. The suite is organised by area instead, and the README table maps each area to its modules so gaps are visible without tooling. Adding `pytest-cov` is a one-line change once approved.

## M0-5. No migrations run in Milestone 0

**Decision.** The database is reachable but empty. `migrate` is deliberately not run yet.

**Why.** `docs/schema.md` specifies a custom `User` model. Django requires `AUTH_USER_MODEL` to be set before the first migration; running the default `auth` migrations now would force a database reset at Milestone 1, which is a destructive action gated for approval. Deferring the first `migrate` to Milestone 1 (after Gate 2 sign-off on the models) avoids that entirely.

## M0-6. Frontend is deliberately thin: plain JSX, no UI library, no router yet

**Decision.** Vite + React with hand-written CSS. `src/api.js` is the single place that knows the backend URL. React Router is added in Milestone 2 when the homeowner and ops surfaces appear.

**Why.** The brief is explicit that the backend is the portfolio focus and the frontend exists to demo it. Every dependency added to the frontend is a dependency to maintain and explain; none are needed to show the backend working.

## M0-7. CORS and CSRF trusted origins come from one variable

**Decision.** `CORS_ALLOWED_ORIGINS` (comma-separated env var) feeds both `django-cors-headers` and `CSRF_TRUSTED_ORIGINS`, with `CORS_ALLOW_CREDENTIALS = True`.

**Why.** The SPA and the API are on different origins in every environment (5173 vs 8000 locally; Vercel vs the backend host in production). Keeping the list in one variable means a deploy needs exactly one value changed, and the API can support either cookie/session or token auth at Gate 3 without a settings change.

## M0-8. Celery pool on Windows

**Note for Milestone 5.** Celery's default prefork pool does not run on Windows. Locally the worker will start with `--pool=solo`; production hosts are Linux and use the default. This is a local dev flag only and will be documented in the run instructions.

---

## M1-1. Three Django apps: `accounts`, `applications`, `core`

**Decision.** `accounts` owns the custom `User`. `applications` owns the eight domain tables, the enums, the state machine, and the service layer. `core` holds the abstract base models and the health check.

**Why.** The custom user model must exist in the very first migration; isolating it keeps that migration tiny and stable. Everything else lives together because the domain tables are tightly coupled (every child cascades from `Application`) and splitting them would only create cross-app migration dependencies.

## M1-2. Cross-table rules are enforced on `save()` and `clean()` and in services

**Rules.** `application.property.owner_id == application.homeowner_id`; `application.suite.property_id == application.property_id`; `assigned_staff` (on Application and Visit) must hold the staff or admin role.

**Decision.** PostgreSQL cannot express these as constraints (they span tables). They are implemented once in `applications/services.py` and called from `Model.clean()` (admin and forms), from `Model.save()` (every ORM write), and will be called again by API serializers. `limit_choices_to` on the FK is a UI hint only and is not relied upon.

**Tradeoff.** Validation on `save()` costs one or two indexed lookups per write. `QuerySet.update()` bypasses it, which is why the service layer is the only place that writes these fields.

## M1-3. Append-only history is an application-level guarantee, not a database one

**Decision.** `ApplicationStatusHistory.save()` refuses updates and `delete()` always raises. Admin shows it read-only. The API will expose no update or delete operation on it.

**Limitation, stated plainly.** This is not equivalent to a PostgreSQL trigger or a revoked `UPDATE`/`DELETE` grant. Bulk `QuerySet.update()`/`.delete()`, raw SQL, or a superuser at `psql` can still modify rows. It is also deliberately compatible with the approved schema's `CASCADE`: deleting an application removes its history. A tamper-proof audit trail would add a `BEFORE UPDATE OR DELETE` trigger that raises, plus a separate archival table; that is a reasonable follow-up once the deploy target's database permissions are known.

## M1-4. Four extra CHECK constraints beyond the spec

`property_year_built_reasonable` (null or 1800 to 2100), `application_cost_non_negative`, `permit_approved_not_before_applied` (only checked when both dates are set), `document_file_present_unless_required`. Each is tested for its null case and its boundary values. They protect against data that the UI would never produce but a buggy import or a bad API call could.

## M1-5. Composite index for the ops queue

Beyond the single-column indexes the spec lists, `application_queue_idx` covers `(status, created_at DESC)`. The ops queue's default view is "open leads, newest first, filtered by status"; a composite index serves that query directly instead of intersecting two single-column indexes.

## M1-6. On-hold resume is derived from history

`on_hold` may only return to the status it left. Rather than adding a `previous_status` column, the transition service reads the last history row whose `to_status` is `on_hold` and uses its `from_status`. The history table is already the audit source of truth, so this avoids a second copy of the same fact that could drift.

## M1-7. Seeding compliance items and required documents is a service, not a signal

`docs/schema.md` asks for the standard compliance set and the required documents to be created when an application is created. This will run inside the same `transaction.atomic()` block as the application insert (Milestone 3). Django signals would run the same code but hide the transaction boundary and make the all-or-nothing behaviour harder to test.

## M1-8. Tests run only against PostgreSQL

`pytest-django` creates and drops a `test_ready2rent` database on the local Postgres container for each run. There is no SQLite test path, because the point of most tests is to prove Postgres constraint, index, and cascade behaviour.

---

## M2-1. JWT with the access token in memory and the refresh token in an HttpOnly cookie

**Decision.** Login returns a 30-minute access token in the JSON body; the SPA keeps it in a module-level variable and never writes it to `localStorage` or `sessionStorage`. The 7-day refresh token is returned only as an `HttpOnly` cookie scoped to path `/api/auth/`, `SameSite=Lax`, `Secure` outside DEBUG. On page load the SPA calls the refresh endpoint to obtain a new access token. Refresh tokens rotate on every use and the previous one is blacklisted (simplejwt `token_blacklist`, approved as third-party auth infrastructure).

**Why.** A token in web storage is readable by any script that runs on the page, so one XSS bug leaks a long-lived credential. An `HttpOnly` cookie is invisible to scripts; the worst an XSS bug can do is use the session while the page is open. Rotation plus blacklisting bounds the damage of a leaked refresh token to one use.

## M2-2. Same-origin API access is a deployment requirement

**Decision.** The browser always reaches the API at `/api` on its own origin. Locally the Vite dev server proxies `/api` to Django (`frontend/vite.config.js`, target from `VITE_API_PROXY_TARGET`). In production either (a) the frontend host rewrites `/api/*` to the backend host (Vercel `rewrites`, Netlify `_redirects` with status 200), or (b) the app and API run on sibling subdomains of one registrable domain (`app.example.com` / `api.example.com`) with `AUTH_COOKIE_DOMAIN`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` set explicitly.

**Why.** Cookie auth across unrelated domains needs third-party cookies, which Safari blocks and Chrome is phasing out. Same-origin (or same-site) keeps the refresh and CSRF cookies first-party everywhere. Consequence: `CORS_ALLOWED_ORIGINS` is empty by default and there is never a wildcard origin with credentials.

## M2-3. CSRF is enforced explicitly on the cookie-authenticated endpoints

**Decision.** DRF views are exempt from Django's CSRF middleware (DRF enforces CSRF only inside `SessionAuthentication`, which this project does not use). The refresh and logout views therefore run Django's `CsrfViewMiddleware` check directly, which validates the `X-CSRFToken` header against the `csrftoken` cookie and validates the `Origin`/`Referer` header against the request host and `CSRF_TRUSTED_ORIGINS`. `GET /api/auth/csrf/` issues the cookie on a cold load; login and register re-issue it.

**Why.** Only requests authenticated by a cookie can be forged cross-site. Bearer-token endpoints are immune because a third-party page cannot read the in-memory token.

## M2-4. Logout is best-effort revocation plus unconditional cookie clearing

Logout requires no access token (it may have expired), attempts to blacklist the refresh token, swallows token errors, logs infrastructure errors, and always sends the cookie deletion. A user can always end their session in the browser even if Redis or Postgres is down.

## M2-5. Login failures are indistinguishable

Unknown email, wrong password, and inactive account all return `401 {"detail": "Invalid email or password."}` with no cookie. Django's `ModelBackend` already returns `None` for inactive users, so the three cases collapse into one branch by construction, and a test asserts the three responses are identical.

## M2-6. Throttling is Redis-backed abuse reduction, not brute-force protection

**Decision.** Login and register are limited to 10 requests per minute per client IP and refresh to 60, using DRF's `ScopedRateThrottle` over the default cache, which is Redis. Counters are therefore shared by every API process. `DJANGO_NUM_PROXIES` tells DRF how many trusted proxies to strip from `X-Forwarded-For`; it is 0 locally and must equal the real proxy count in production, otherwise every client shares one bucket or an attacker can spoof the header.

**Limitation.** Per-IP throttling slows credential stuffing but does not stop a distributed attack. Real brute-force protection means per-account lockout or progressive delays, breached-password checks, and MFA; those are production follow-ups.

## M2-7. Django admin-site access is derived from the application role

`User.save()` sets `is_staff = (role == admin)` on every save, including `update_fields` saves, and the admin shows `is_staff` read-only. Only admin-role accounts can log in to `/admin/`. Registration cannot set role; the profile endpoint ignores `role`, `email`, `is_staff`, and `is_superuser`. Tests attempt each escalation path and assert it fails. Staff and admin accounts are created only by an admin through Django admin.

## M2-8. Staff self-claim is deferred to a dedicated locked action

Approved rule: staff may claim only an unassigned application; only admins may assign or reassign to another user. This will be one service function under `select_for_update()` in Milestone 4, not a generic writable `assigned_staff` field.

## M2-9. Deferred production requirements (need Gate 4: external email)

- **Password reset by email.** Not implemented; needs an email provider and Gate 4 approval for its credentials.
- **Email verification on signup.** Same dependency. Until then, accounts are usable immediately after registration.

Both are recorded here so they are not forgotten before a public launch.

---

## M3-1. Intake is one request and one transaction

**Decision.** The React wizard collects four steps client-side and submits once. `services.submit_intake()` creates Property, Suite, and Application, seeds the eight standard compliance items (plus an `other` item if the homeowner described extra issues), seeds the required documents, and writes the first history row, all inside a single `transaction.atomic()`. A test injects a failure into document seeding and asserts no Property, Suite, Application, ComplianceItem, or history row survives.

**Why.** Transaction boundary 1 in `docs/schema.md`. A half-created application (no checklist, no history) would look like a bug to ops and could not be recovered by the homeowner. Saving drafts per step would need a draft state that the schema does not have; the wizard state lives in the browser until submit instead.

## M3-2. Homeowner self-assessment seeds the compliance checklist

Homeowners answer each standard code item with "meets", "needs work", or "not sure", which map to `compliant`, `needs_work`, and `not_assessed`. `na` is reserved for ops. Items the homeowner answers get a note saying they were self-reported, so staff know the status is a claim, not an assessment. The separate-entrance question on the suite doubles as the answer for that compliance item unless answered directly.

## M3-3. Goals live in the first history note, not new columns

The intake captures "interested in the incentive" (a real column, `pursuing_incentive`), "wants financing guidance", and free-text goals. The schema has no column for the last two, and adding one would reopen Gate 2, so they are written into the note on the first `ApplicationStatusHistory` row. That row is append-only and shown to ops, which is exactly what an intake message should be. Financing stays a "connect / guide" request per `docs/domain-research.md` §7; the software never originates or brokers anything.

## M3-4. Required documents are a pure function of suite type and year built

`applications/documents.py` computes the set from the domain research: the common seven for everyone, elevations for new builds only, colour photos for legalizing an existing suite, and the asbestos form when `year_built < 1990`. Being a pure function, it is unit-tested at the boundaries (1989 vs 1990, unknown year) independently of the API.

## M3-5. Uploaded documents are never public

**Decision.** The `MEDIA_URL` static route was removed even for DEBUG. Files are stored under `MEDIA_ROOT` with an unguessable path (`applications/<uuid>/<doc_type>/<name>`), but the only way to read one is the authenticated, ownership-checked download view, which streams it as an attachment. A test requests the raw media path and expects 404.

**Why.** An unguessable URL is not access control; anyone who is ever shown the path (a log, a browser history, a support screenshot) could fetch a land title. Serving through the API also means swapping local disk for S3-compatible storage later changes only the storage backend, not the security model.

## M3-6. Upload validation: allow-list plus magic bytes, no library

PDF, PNG, and JPEG only, checked by extension and by leading bytes, with a size cap from `MAX_UPLOAD_MB` and an empty-file check. Accepted documents are locked; required, uploaded, and rejected ones can be replaced, and the previous file is deleted from storage on replace. Deeper inspection (Pillow decoding, PDF parsing, antivirus) is deliberately out of scope: it adds dependencies and still cannot prove a file is benign. What the check does guarantee is that a renamed executable is refused.

## M3-7. Ownership is enforced twice on the homeowner surface

Every homeowner view builds its queryset from `homeowner = request.user` (documents through `application__homeowner`), so foreign rows are 404 and existence is never revealed. Independently, `IsApplicationOwner` re-checks the loaded object, so a future queryset bug cannot leak data. A test exercises the object permission directly against a foreign application and a foreign document.

## M3-8. The row-locked transition service arrives now, used by withdraw

`services.transition_application()` implements transaction boundary 2: `select_for_update()` on the Application, validate against the state machine (resolving the on-hold prior status from history), update, append history. The homeowner withdraw action is its first caller; Milestone 4's ops actions reuse it unchanged. A two-thread test on a real Postgres connection proves that when two callers race the same transition, exactly one succeeds and exactly one history row is written.

## M3-9. History shown to homeowners hides staff identity

The homeowner-facing serializer exposes only whether a change was made by "you" or by "ready2rent". Staff emails and names never leave the ops surface.

---

## M4-1. "Read all, act on assigned" is one object permission, applied to child rows too

**Decision.** `CanActOnApplication` allows any ops user to read, lets an admin write anything, and lets a staff member write only when `application.assigned_staff_id` is their own id. Child views (compliance items, permits, visits, document review) resolve the permission through the child's `application`, so the rule cannot be bypassed by editing a permit instead of the application.

**Why.** The spec's access rule is short, and one class that every ops write view declares is easier to audit than per-view checks. Tests exercise an unassigned staff member against every write endpoint and expect 403 with no side effects.

## M4-2. Claim and assign are separate, row-locked services

**Decision.** `claim_application()` locks the row, refuses if anyone is already assigned, and assigns the caller. `assign_application()` is admin-only and may set, change, or clear the assignee. Neither is a writable `assigned_staff` field on a PATCH.

**Why.** Two staff opening the same new lead and both clicking "claim" is the most likely race in the product. `select_for_update()` serialises them so exactly one wins, which a two-thread test on real Postgres connections proves. Keeping "claim" and "assign" as distinct verbs also keeps the authorization rule simple: claim is for yourself and only when nobody owns the lead; anything else is an admin decision.

## M4-3. Notes and assignments are history rows with an unchanged status

**Decision.** Internal notes, claims, assignments, and document-review summaries are written as `ApplicationStatusHistory` rows whose `from_status` equals `to_status`. The homeowner serializer excludes those rows; the ops serializer flags them with `is_note`.

**Why.** The schema asks for assignment to carry an optional history note and for staff to add notes, but has no separate notes table. Reusing the append-only history keeps one chronological audit log per application, written by the same locked services. The trade-off is that a status row and a note row share a table; the `from == to` convention and the ops UI's "Note" label keep them distinguishable. If notes ever need attachments or threading, they become their own table.

## M4-4. Completion is gated by real evidence, checked under the lock

**Decision.** A transition to `registered` or `complete` runs `completion_blockers()` inside the same locked transaction as the state-machine check. It requires at least one permit recorded, every permit that is not `not_required` to be `approved`, at least one inspection visit `completed`, and no inspection still `scheduled`. Site assessments do not count as inspections. The detail endpoint exposes the current blockers so the UI can show staff what is missing before they try.

**Why.** Transaction boundary 4 in the schema. Checking outside the lock would let a permit be downgraded between the check and the write.

## M4-5. Bulk document review is all-or-nothing and rejections need a note

**Decision.** `review_documents()` locks the application and the selected document rows, validates every decision first (document belongs to this application, has a file, rejection carries a note), and only then writes. One bad decision fails the whole batch with a list of reasons. A single summary history row records the review.

**Why.** Transaction boundary 5 in the schema. A rejection without a reason produces a support call; making the note mandatory turns the review into feedback the homeowner can act on, and the homeowner sees that note on the rejected row.

## M4-6. Queue counts are computed by the database, not the API

The queue annotates documents awaiting review, required and uploaded document counts, and code items needing work with conditional `Count()` aggregates in one query, ordered by the composite index from Milestone 1. This is the query Milestone 5 caches in Redis.

## M4-7. Only the schema's ops-editable scalars are writable

The ops PATCH accepts estimated cost, the incentive flag, and the property's land use district (set during the eligibility check per the domain research). Status, homeowner, property, and suite are never writable through the API; status moves only through the transition service.

---

## M5-1. Queue cache uses versioned keys, not key deletion

**Decision.** Every cached queue page and summary embeds a version integer stored in Redis. A write bumps the version with one `INCR`; old entries are simply never read again and expire on their own TTL. There is no key scanning and no per-filter bookkeeping.

**Why.** The queue has many filter combinations and pages. Deleting the right subset on each write is error-prone; deleting everything requires `SCAN` or `KEYS`, which are slow or unsafe on a shared Redis. One counter invalidates all of it in O(1).

**Trade-off.** Any write to any application invalidates every queue page, even pages that would not have changed. At this volume (tens of leads a day, a handful of staff) that costs one extra database query per staff view after each write, which is nothing; at much higher volume the counter could be per-status or per-assignee.

## M5-2. Invalidate twice: immediately and on commit

A reader that runs between a write's cache bump and its transaction commit would repopulate the cache with pre-commit data. Bumping again in `transaction.on_commit()` closes that window. Both bumps are cheap, and the TTL is the final backstop.

## M5-3. Invalidation is driven by model signals

Signals are avoided elsewhere in this project because they hide transaction boundaries. Cache invalidation is the exception: the requirement is "never miss a write", including edits through Django admin or a management shell, and a signal on every model that feeds the queue is the only way to guarantee that. The signal handler does nothing but bump a counter, so there is no hidden business logic.

## M5-4. Personal views are cached per user; shared views are shared

Cache keys include the user id only when the response depends on who asks: `assigned=me` and the summary's `mine` count. Everything else is shared across staff, so one staff member's read warms the cache for the others. A test asserts that two staff members' `assigned=me` views never collide.

## M5-5. Cache failure degrades to the database

Every cache read, write, and version lookup catches exceptions and logs them. If Redis is down the queue is served uncached and slower, never broken. A test patches the cache client to raise and asserts a 200 with correct data.

## M5-6. Tasks are enqueued after commit, and enqueue failure never fails the request

**Decision.** Services call `transaction.on_commit()` to enqueue Celery tasks, wrapped so a broker error is logged rather than raised. Tasks receive ids, not objects, and re-read the row; a missing row is a no-op.

**Why.** Enqueuing inside the transaction would let a worker pick up the task before the row is visible, or send an email for a write that then rolls back. Tests cover both: a rolled-back intake sends nothing, and a transition still succeeds when the broker is unreachable.

## M5-7. Notification policy

Staff are emailed on every new lead (all active ops users, since nobody owns it yet). When a homeowner uploads a document or withdraws, the assigned staff member is told, or all ops if unassigned. The homeowner is emailed on every status change made by staff, with the note if one was written, and after a document review with the rejection reasons. Internal notes send nothing. Tasks retry with exponential backoff, at most three times, and are acknowledged late so a worker crash mid-send re-queues the task rather than losing it.

## M5-8. Celery worker on Windows uses the solo pool

Celery's default prefork pool relies on `fork()`, which Windows lacks. Locally the worker runs with `--pool=solo` (one task at a time, in-process). Production hosts are Linux and use the default. Documented in the README run steps.

## M5-9. Django 6.x `MAILERS` instead of the deprecated `EMAIL_*` settings

Django 6.1 deprecates `EMAIL_BACKEND` and friends in favour of a `MAILERS` dict. Settings build that dict from the same `EMAIL_*` environment variables, so the `.env` contract is unchanged and the test runner's automatic switch to the in-memory backend still applies. This removes six deprecation warnings that would have become errors in Django 7.

## M5-10. Deferred: production email provider (Gate 4)

SMTP host, credentials, and a sending domain are external accounts and need Gate 4 approval. Until then the console backend is the only configured mailer.


---

## M7-2. Vercel + Render, deployed from GitHub

**Decision.** The React build is served by Vercel (free). The backend runs on Render from a Blueprint (`render.yaml`): an always-on Starter web service with a 1 GB persistent disk for uploads, Basic PostgreSQL, and a free Key Value (Redis) instance. Both hosts redeploy on push to `main`.

**Why.** Recruiters must get an instant load, so nothing that serves a request is allowed to sleep: the SPA is static on Vercel's CDN and the API is on an always-on instance. A Blueprint keeps the whole backend reproducible from one reviewed file instead of dashboard clicks.

**Cost trade-offs.** Notification tasks run in-process (`CELERY_TASK_ALWAYS_EAGER=true`) rather than on a paid worker instance; they only print console emails, so a separate worker adds cost without visible benefit for a demo. The worker is one uncommented block away. A persistent disk instead of object storage avoids new dependencies but pins the service to one instance with brief downtime on deploy, which is acceptable for a demo.

## M7-3. Admin role implies Django superuser

`User.save()` now derives both `is_staff` and `is_superuser` from `role == admin`, including on `update_fields` saves, and both are read-only in the admin. An admin-role account created any way has full Django admin access; demoting it revokes both flags. Tests cover promotion, demotion, and that no API can grant the flag.

## M7-4. Coverage measured with pytest-cov

`pytest --cov` reports 97% line coverage across `accounts`, `applications`, `core`, and `config` (migrations, tests, and WSGI/ASGI entry points excluded by `.coveragerc`). The uncovered lines are mostly production-only settings branches and defensive exception handlers.

## M7-5. Production behaviour behind the /api proxy

- **Origins.** Vercel forwards `/api/*` to Render, so Django sees its own hostname in `Host` (added from `RENDER_EXTERNAL_HOSTNAME`) while the browser's `Origin` is the Vercel URL. `USE_X_FORWARDED_HOST` is off and the Vercel origin is trusted explicitly through `CSRF_TRUSTED_ORIGINS`.
- **No shared caching of API responses.** Every `/api/` response carries `Cache-Control: no-store, private`, and `vercel.json` disables rewrite caching for `/api/*`. Without this, a CDN honouring upstream cache headers could serve one user's data to another.
- **Liveness before host checks.** Platform health checks use internal hosts and plain HTTP. A first-position middleware answers `/api/livez/` (which returns nothing but `{"status": "ok"}`) before `ALLOWED_HOSTS` validation and the HTTPS redirect. Every other path still validates the host.
- **Throttle identity.** With `DJANGO_NUM_PROXIES=0`, DRF keys throttles on the whole `X-Forwarded-For` chain. This guarantees visitors behind the Vercel proxy never collapse into one shared bucket, which would lock recruiters out of login. The accepted cost is that someone rotating that header can evade per-IP limits; per-account lockout would close it.
- **CSP.** The built `index.html` loads one module script and one stylesheet and contains no inline code, so the policy allows only `'self'` for scripts and styles.
