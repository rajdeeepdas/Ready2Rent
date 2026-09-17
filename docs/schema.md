# Ready2Rent — Database Schema Specification

Source of truth for the data model. Claude Code implements Django models and migrations from this at Gate 2 (after presenting them back for approval). Money uses `DecimalField` (never float). All PKs are UUIDs. All tables have `created_at`; mutable tables also have `updated_at`.

See `docs/domain-research.md` for why these fields exist. ER diagram: `ready2rent-erd.mermaid`.

---

## Enumerations (Django TextChoices)
- **UserRole:** `homeowner`, `staff`, `admin`
- **SuiteType:** `new`, `legalize_existing`
- **ApplicationStatus:** `intake`, `eligibility_check`, `development_permit`, `permits`, `construction`, `inspections`, `registered`, `complete`, `on_hold`, `withdrawn`
- **ComplianceItemType:** `egress_window`, `ceiling_height`, `fire_separation`, `smoke_co_alarms`, `separate_entrance`, `mechanical_separation`, `parking`, `amenity_space`, `other`
- **ComplianceStatus:** `not_assessed`, `needs_work`, `compliant`, `na`
- **PermitType:** `development`, `building`, `electrical`, `plumbing`, `gas`, `mechanical`
- **PermitStatus:** `not_required`, `not_started`, `applied`, `approved`, `rejected`, `expired`
- **DocumentType:** `application_form`, `site_plan`, `floor_plans`, `elevations`, `abandoned_well_declaration`, `site_contamination_statement`, `public_tree_disclosure`, `asbestos_abatement`, `colour_photos`, `land_title`, `other`
- **DocumentStatus:** `required`, `uploaded`, `accepted`, `rejected`
- **VisitType:** `site_assessment`, `inspection`
- **VisitStatus:** `scheduled`, `completed`, `cancelled`, `no_show`

---

## Tables

### User
Custom user model (extend `AbstractUser`; auth/password handled by Django).

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| email | Email | **unique**, login field |
| role | enum UserRole | default `homeowner` |
| first_name, last_name | Char | |
| phone | Char | nullable |
| is_active | Bool | default true |
| date_joined | DateTime | auto |

Indexes: `email` (unique), `role`.

### Property
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| owner | FK → User | `on_delete=PROTECT`; related_name `properties` |
| street_address | Char | |
| city | Char | default "Calgary" |
| province | Char | default "AB" |
| postal_code | Char | |
| land_use_district | Char | nullable; set during eligibility check; drives whether a DP is required |
| year_built | Int | nullable; `< 1990` triggers required asbestos_abatement doc |
| created_at / updated_at | DateTime | auto |

Indexes: `owner`.

### Suite
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| property | FK → Property | `on_delete=CASCADE`; related_name `suites` |
| suite_type | enum SuiteType | drives required docs + compliance flow |
| has_separate_entrance | Bool | nullable during intake |
| description | Text | blank ok |
| created_at / updated_at | DateTime | auto |

### Application
The central workflow record (the "lead" in the ops UI).

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| homeowner | FK → User | `on_delete=PROTECT`; related_name `applications` |
| property | FK → Property | `on_delete=PROTECT` |
| suite | OneToOne → Suite | `on_delete=PROTECT`; one active application per suite |
| assigned_staff | FK → User | nullable; `on_delete=SET_NULL`; staff/admin only |
| status | enum ApplicationStatus | default `intake`; transitions validated in code |
| pursuing_incentive | Bool | default false (program winding down) |
| estimated_cost | Decimal(10,2) | nullable |
| submitted_at | DateTime | nullable; set when homeowner submits intake |
| created_at / updated_at | DateTime | auto |

Indexes: `status`, `assigned_staff`, `homeowner`, `created_at` (back the ops queue + later Redis cache).

### ApplicationStatusHistory
**Append-only.** No updates, no deletes.

| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| application | FK → Application | `on_delete=CASCADE`; related_name `status_history` |
| from_status | enum ApplicationStatus | nullable (first row) |
| to_status | enum ApplicationStatus | |
| changed_by | FK → User | `on_delete=PROTECT` |
| note | Text | blank ok |
| created_at | DateTime | auto |

Indexes: `application`, `created_at`.

### ComplianceItem
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| application | FK → Application | `on_delete=CASCADE`; related_name `compliance_items` |
| item_type | enum ComplianceItemType | |
| status | enum ComplianceStatus | default `not_assessed` |
| notes | Text | blank ok |
| created_at / updated_at | DateTime | auto |

Constraint: unique together `(application, item_type)` except `other`. Seed the standard set on application creation.

### Permit
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| application | FK → Application | `on_delete=CASCADE`; related_name `permits` |
| permit_type | enum PermitType | |
| permit_number | Char | nullable |
| status | enum PermitStatus | default `not_started` |
| applied_date / approved_date | Date | nullable |
| notes | Text | blank ok |
| created_at / updated_at | DateTime | auto |

Constraint: unique together `(application, permit_type)`.

### Document
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| application | FK → Application | `on_delete=CASCADE`; related_name `documents` |
| doc_type | enum DocumentType | |
| file | File | nullable until uploaded; stored under Django `MEDIA_ROOT` locally (a cloud object store can be swapped in later) |
| status | enum DocumentStatus | default `required` |
| uploaded_by | FK → User | nullable; `on_delete=SET_NULL` |
| uploaded_at | DateTime | nullable |
| notes | Text | blank ok |
| created_at / updated_at | DateTime | auto |

The **required set** is computed at intake from `suite.suite_type` and `property.year_built` (asbestos if pre-1990; colour_photos if legalize_existing). Seed these as `status=required` rows.

### Visit
| Field | Type | Notes |
|---|---|---|
| id | UUID | PK |
| application | FK → Application | `on_delete=CASCADE`; related_name `visits` |
| visit_type | enum VisitType | |
| scheduled_for | DateTime | |
| assigned_staff | FK → User | nullable; `on_delete=SET_NULL` |
| status | enum VisitStatus | default `scheduled` |
| outcome_notes | Text | blank ok |
| created_at / updated_at | DateTime | auto |

Indexes: `application`, `scheduled_for`.

---

## Relationships & on_delete rationale
- **Application children (StatusHistory, ComplianceItem, Permit, Document, Visit) → CASCADE:** meaningless without their application.
- **Homeowner / Property / Suite on Application → PROTECT:** can't delete a person or property with a live application.
- **assigned_staff / uploaded_by → SET_NULL:** a staff member leaving keeps the record, drops the pointer.
- **changed_by on history → PROTECT:** preserve who made each audited change.

---

## Status state machine (enforce in code)
```
intake            -> eligibility_check, withdrawn
eligibility_check -> development_permit, permits, on_hold, withdrawn
development_permit-> permits, on_hold, withdrawn
permits           -> construction, on_hold, withdrawn
construction      -> inspections, on_hold, withdrawn
inspections       -> registered, construction (rework), on_hold, withdrawn
registered        -> complete
on_hold           -> (return to prior state), withdrawn
```
Reject any transition not in this map. `eligibility_check -> permits` (skipping DP) is valid only when the district permits a suite by right.

---

## Transaction boundaries (wrap each in `transaction.atomic()`)
1. **Create application (intake submit):** create Application + seed ComplianceItems + seed required Documents + first StatusHistory row. All or nothing.
2. **Status transition:** `select_for_update()` the Application row → validate the transition → update `status` → insert StatusHistory row.
3. **Assign / reassign staff:** update `assigned_staff` (+ optional history note) atomically.
4. **Mark Registered/Complete:** under `select_for_update()`, verify all required Permits `approved` and required inspection Visits `completed`, then transition.
5. **Bulk document review:** accept/reject multiple documents in one committed action.

Use row locks (`select_for_update`) anywhere two staff could act on the same application concurrently.

---

## Access control (spec for the API layer)
- Homeowners: read/write only rows reachable from `homeowner = self`. Never see other homeowners; never reach staff endpoints.
- Staff/admin: read all applications; act on assigned ones (admin: any).
- Enforce at the queryset level (filter by role), not just the UI.

---

## Interview notes (for DECISIONS.md)
- UUID PKs prevent ID enumeration on homeowner-facing URLs.
- Append-only history + atomic transitions = tamper-evident audit trail with no torn writes.
- `select_for_update` over optimistic concurrency: staff actions are low-volume; correctness on a single hot row matters more than throughput.
- Deliberate on_delete policy per relationship reflects data lifecycle, not defaults.
- Permit is its own table (not booleans) because the real process runs several independent permits with distinct statuses.
