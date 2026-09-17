"""
Service layer: validation rules PostgreSQL cannot express, and the transactional
operations from docs/schema.md "Transaction boundaries".

Rules that span tables are enforced in three places so no code path can skip them:
  1. Model.clean()  -> Django admin and any full_clean() caller
  2. Model.save()   -> every ORM save (calls the same functions below)
  3. API serializers / services -> call the same functions
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import tasks
from .documents import required_document_types

logger = logging.getLogger(__name__)


def _after_commit(enqueue) -> None:
    """Enqueue a Celery task once the surrounding transaction commits. A broker outage
    must never fail the user's request: the write already happened; log and move on."""

    def _safe():
        try:
            enqueue()
        except Exception:  # noqa: BLE001
            logger.exception("Could not enqueue notification task")

    transaction.on_commit(_safe)
from .enums import (
    ApplicationStatus,
    ComplianceItemType,
    ComplianceStatus,
    DocumentStatus,
    DocumentType,
)
from .state_machine import InvalidTransition, validate_transition

# ---------------------------------------------------------------------------
# Cross-table validation (Milestone 1)
# ---------------------------------------------------------------------------


def validate_ops_user(user, *, field: str = "assigned_staff") -> None:
    """The user must hold the staff or admin role."""
    if user is None:
        return
    if not user.is_ops:
        raise ValidationError({field: "Assigned user must have the staff or admin role."})


def validate_application_links(application) -> None:
    """
    Cross-table consistency for an Application:
      - property.owner_id  == homeowner_id
      - suite.property_id  == property_id
    Uses *_id comparisons so it never depends on cached related instances.
    """
    errors = {}

    if application.property_id and application.homeowner_id:
        owner_id = (
            type(application).property.field.related_model.objects.filter(pk=application.property_id)
            .values_list("owner_id", flat=True)
            .first()
        )
        if owner_id != application.homeowner_id:
            errors["property"] = "Property must belong to the application's homeowner."

    if application.suite_id and application.property_id:
        suite_property_id = (
            type(application).suite.field.related_model.objects.filter(pk=application.suite_id)
            .values_list("property_id", flat=True)
            .first()
        )
        if suite_property_id != application.property_id:
            errors["suite"] = "Suite must belong to the application's property."

    if errors:
        raise ValidationError(errors)


def validate_application(application) -> None:
    """All service-level rules for an Application, in one call."""
    validate_application_links(application)
    if application.assigned_staff_id:
        validate_ops_user(application.assigned_staff)


def validate_visit(visit) -> None:
    if visit.assigned_staff_id:
        validate_ops_user(visit.assigned_staff)


# ---------------------------------------------------------------------------
# Transaction boundary 1: intake submit (Milestone 3)
# ---------------------------------------------------------------------------

STANDARD_COMPLIANCE_ITEMS = [t for t in ComplianceItemType.values if t != ComplianceItemType.OTHER]

# What a homeowner may self-report per item. `na` is an ops-only judgement.
SELF_REPORTABLE_STATUSES = {
    ComplianceStatus.COMPLIANT,
    ComplianceStatus.NEEDS_WORK,
    ComplianceStatus.NOT_ASSESSED,
}


def submit_intake(
    *,
    homeowner,
    property_data: dict,
    suite_data: dict,
    compliance: dict[str, str] | None = None,
    other_issues: str = "",
    pursuing_incentive: bool = False,
    wants_financing_guidance: bool = False,
    goals: str = "",
):
    """
    Create Property + Suite + Application, seed ComplianceItems and required Documents,
    and write the first StatusHistory row. All or nothing.
    """
    from .models import Application, ApplicationStatusHistory, ComplianceItem, Document, Property, Suite

    compliance = compliance or {}
    bad = {k: v for k, v in compliance.items() if v not in SELF_REPORTABLE_STATUSES}
    if bad:
        raise ValidationError({"compliance": f"Invalid self-reported status: {bad}"})
    unknown = [k for k in compliance if k not in STANDARD_COMPLIANCE_ITEMS]
    if unknown:
        raise ValidationError({"compliance": f"Unknown compliance items: {unknown}"})

    with transaction.atomic():
        prop = Property.objects.create(owner=homeowner, **property_data)
        suite = Suite.objects.create(property=prop, **suite_data)
        application = Application.objects.create(
            homeowner=homeowner,
            property=prop,
            suite=suite,
            pursuing_incentive=pursuing_incentive,
            submitted_at=timezone.now(),
        )

        # If the homeowner answered the separate-entrance question directly, use it as the
        # self-report for that compliance item unless they answered the item explicitly.
        if ComplianceItemType.SEPARATE_ENTRANCE not in compliance and suite.has_separate_entrance is not None:
            compliance[ComplianceItemType.SEPARATE_ENTRANCE] = (
                ComplianceStatus.COMPLIANT if suite.has_separate_entrance else ComplianceStatus.NEEDS_WORK
            )

        items = []
        for item_type in STANDARD_COMPLIANCE_ITEMS:
            status = compliance.get(item_type, ComplianceStatus.NOT_ASSESSED)
            items.append(
                ComplianceItem(
                    application=application,
                    item_type=item_type,
                    status=status,
                    notes="Homeowner self-reported at intake." if item_type in compliance else "",
                )
            )
        if other_issues.strip():
            items.append(
                ComplianceItem(
                    application=application,
                    item_type=ComplianceItemType.OTHER,
                    status=ComplianceStatus.NEEDS_WORK,
                    notes=f"Homeowner reported: {other_issues.strip()}",
                )
            )
        ComplianceItem.objects.bulk_create(items)

        Document.objects.bulk_create(
            [
                Document(application=application, doc_type=doc_type, status=DocumentStatus.REQUIRED)
                for doc_type in required_document_types(suite.suite_type, prop.year_built)
            ]
        )

        note_lines = ["Intake submitted by homeowner."]
        if goals.strip():
            note_lines.append(f"Goals: {goals.strip()}")
        note_lines.append(f"Interested in the incentive program: {'yes' if pursuing_incentive else 'no'}.")
        note_lines.append(
            f"Financing guidance requested: {'yes' if wants_financing_guidance else 'no'}."
        )
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status=None,
            to_status=ApplicationStatus.INTAKE,
            changed_by=homeowner,
            note=" ".join(note_lines),
        )

        # Notify staff only once the whole intake has committed.
        _after_commit(lambda: tasks.notify_staff_new_lead.delay(str(application.id)))

    return application


# ---------------------------------------------------------------------------
# Transaction boundary 2: status transition with a row lock (shared by homeowner
# withdraw in Milestone 3 and every ops action in Milestone 4)
# ---------------------------------------------------------------------------


def _prior_status_before_hold(application) -> str | None:
    """For an on_hold application, the status it was in before the hold."""
    from .models import ApplicationStatusHistory

    row = (
        ApplicationStatusHistory.objects.filter(
            application=application, to_status=ApplicationStatus.ON_HOLD
        )
        .order_by("-created_at")
        .first()
    )
    return row.from_status if row else None


def completion_blockers(application) -> list[str]:
    """
    Transaction boundary 4 (docs/schema.md): before an application may become
    `registered` (and therefore `complete`), every permit that is required must be
    approved and the inspection visits must be completed. Returns human-readable reasons.
    """
    from .enums import PermitStatus, VisitStatus, VisitType

    reasons = []
    permits = list(application.permits.all())
    unapproved = [p for p in permits if p.status != PermitStatus.NOT_REQUIRED and p.status != PermitStatus.APPROVED]
    if not permits:
        reasons.append("No permits are recorded; at least a building permit must be approved.")
    for p in unapproved:
        reasons.append(f"{p.get_permit_type_display()} is {p.get_status_display().lower()}, not approved.")

    inspections = [v for v in application.visits.all() if v.visit_type == VisitType.INSPECTION]
    completed = [v for v in inspections if v.status == VisitStatus.COMPLETED]
    open_ = [v for v in inspections if v.status == VisitStatus.SCHEDULED]
    if not completed:
        reasons.append("No inspection visit has been completed.")
    for v in open_:
        reasons.append(f"An inspection scheduled for {v.scheduled_for:%Y-%m-%d} is still open.")
    return reasons


def transition_application(*, application_id, to_status: str, by_user, note: str = ""):
    """
    Lock the Application row, validate the transition against the state machine
    (and the completion requirements for registered/complete), update the status,
    and append a history row. Raises InvalidTransition. Returns the refreshed Application.
    """
    from .models import Application, ApplicationStatusHistory

    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        prior = None
        if application.status == ApplicationStatus.ON_HOLD:
            prior = _prior_status_before_hold(application)
        validate_transition(application.status, to_status, prior_status=prior)

        if to_status in (ApplicationStatus.REGISTERED, ApplicationStatus.COMPLETE):
            blockers = completion_blockers(application)
            if blockers:
                raise InvalidTransition(application.status, to_status, " ".join(blockers))

        from_status = application.status
        application.status = to_status
        application.save(update_fields=["status", "updated_at"])
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status=from_status,
            to_status=to_status,
            changed_by=by_user,
            note=note,
        )

        app_id = str(application.id)
        if by_user.is_ops:
            _after_commit(lambda: tasks.email_homeowner_status_change.delay(app_id, from_status, to_status, note))
        else:
            # Homeowner-initiated change (withdraw): staff need to know.
            label = dict(ApplicationStatus.choices).get(to_status, to_status)
            _after_commit(lambda: tasks.notify_staff_homeowner_action.delay(app_id, f"Homeowner set status to {label}"))
    return application


def allowed_transitions(application) -> list[str]:
    """Targets the state machine permits from the application's current status."""
    from .state_machine import TRANSITIONS

    if application.status == ApplicationStatus.ON_HOLD:
        prior = _prior_status_before_hold(application)
        return ([prior] if prior else []) + [ApplicationStatus.WITHDRAWN]
    return sorted(TRANSITIONS.get(application.status, ()))


# ---------------------------------------------------------------------------
# Transaction boundary 3: assignment (Milestone 4)
# ---------------------------------------------------------------------------


class AssignmentConflict(Exception):
    """Claim attempted on an application that already has an owner."""


def _note_row(application, by_user, note: str):
    """A history row that records a note without changing status (from == to)."""
    from .models import ApplicationStatusHistory

    return ApplicationStatusHistory.objects.create(
        application=application,
        from_status=application.status,
        to_status=application.status,
        changed_by=by_user,
        note=note,
    )


def claim_application(*, application_id, by_user):
    """Staff self-claim: only an UNASSIGNED application, only to oneself, under a row lock."""
    from .models import Application

    validate_ops_user(by_user, field="claimer")
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        if application.assigned_staff_id is not None:
            raise AssignmentConflict("This application is already assigned.")
        application.assigned_staff = by_user
        application.save(update_fields=["assigned_staff", "updated_at"])
        _note_row(application, by_user, f"Claimed by {by_user.get_full_name() or by_user.email}.")
    return application


def assign_application(*, application_id, staff, by_user, note: str = ""):
    """Admin assignment / reassignment / unassignment (staff=None), under a row lock."""
    from .models import Application

    if staff is not None:
        validate_ops_user(staff)
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        previous = application.assigned_staff
        application.assigned_staff = staff
        application.save(update_fields=["assigned_staff", "updated_at"])
        who = (staff.get_full_name() or staff.email) if staff else "nobody (unassigned)"
        prev = (previous.get_full_name() or previous.email) if previous else "unassigned"
        text = f"Assigned to {who} (was {prev})."
        if note.strip():
            text += f" {note.strip()}"
        _note_row(application, by_user, text)
    return application


def add_note(*, application_id, by_user, note: str):
    from .models import Application

    if not note.strip():
        raise ValidationError({"note": "Note cannot be empty."})
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        row = _note_row(application, by_user, note.strip())
    return row


# ---------------------------------------------------------------------------
# Transaction boundary 5: bulk document review (Milestone 4)
# ---------------------------------------------------------------------------


def review_documents(*, application_id, decisions: list[dict], by_user):
    """
    Accept / reject several documents in one committed action. `decisions` is a list of
    {"document_id": ..., "status": "accepted"|"rejected", "notes": str}. Any invalid item
    (unknown document, document without a file, rejection without a note) fails the whole batch.
    """
    from .models import Application, Document

    if not decisions:
        raise ValidationError({"decisions": "At least one decision is required."})

    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        wanted = {str(d["document_id"]): d for d in decisions}
        docs = {str(doc.pk): doc for doc in Document.objects.select_for_update().filter(application=application, pk__in=wanted)}
        missing = sorted(set(wanted) - set(docs))
        if missing:
            raise ValidationError({"decisions": f"Unknown documents for this application: {missing}"})

        errors = []
        for doc_id, decision in wanted.items():
            doc = docs[doc_id]
            new_status = decision["status"]
            if new_status not in (DocumentStatus.ACCEPTED, DocumentStatus.REJECTED):
                errors.append(f"{doc.get_doc_type_display()}: status must be accepted or rejected.")
                continue
            if not doc.file:
                errors.append(f"{doc.get_doc_type_display()}: nothing has been uploaded yet.")
                continue
            note = (decision.get("notes") or "").strip()
            if new_status == DocumentStatus.REJECTED and not note:
                errors.append(f"{doc.get_doc_type_display()}: a rejection needs a note for the homeowner.")
                continue
            doc.status = new_status
            if note:
                doc.notes = note
            doc.save(update_fields=["status", "notes", "updated_at"])
        if errors:
            raise ValidationError({"decisions": errors})

        summary = ", ".join(
            f"{docs[i].get_doc_type_display()} {wanted[i]['status']}" for i in wanted
        )
        _note_row(application, by_user, f"Documents reviewed: {summary}.")

        payload = [
            {"doc_type": docs[i].doc_type, "status": wanted[i]["status"], "notes": (wanted[i].get("notes") or "").strip()}
            for i in wanted
        ]
        app_id = str(application.id)
        _after_commit(lambda: tasks.email_homeowner_documents_reviewed.delay(app_id, payload))
    return [docs[i] for i in wanted]


def withdraw_application(*, application_id, by_user, note: str = ""):
    return transition_application(
        application_id=application_id,
        to_status=ApplicationStatus.WITHDRAWN,
        by_user=by_user,
        note=note or "Withdrawn by homeowner.",
    )


# ---------------------------------------------------------------------------
# Documents (Milestone 3)
# ---------------------------------------------------------------------------

UPLOADABLE_STATUSES = {DocumentStatus.REQUIRED, DocumentStatus.UPLOADED, DocumentStatus.REJECTED}


class DocumentLocked(Exception):
    """The document has been accepted by staff and can no longer be replaced."""


def upload_document(*, document, uploaded_file, by_user):
    """Attach (or replace) the file on a seeded document row. Accepted documents are locked."""
    from .documents import validate_upload

    validate_upload(uploaded_file)
    if document.status not in UPLOADABLE_STATUSES:
        raise DocumentLocked("This document has already been accepted and cannot be replaced.")

    with transaction.atomic():
        if document.file:
            document.file.delete(save=False)  # drop the previous upload from storage
        document.file.save(uploaded_file.name, uploaded_file, save=False)
        document.status = DocumentStatus.UPLOADED
        document.uploaded_by = by_user
        document.uploaded_at = timezone.now()
        document.save()
        app_id = str(document.application_id)
        label = document.get_doc_type_display()
        _after_commit(lambda: tasks.notify_staff_homeowner_action.delay(app_id, f"Uploaded {label}"))
    return document


def add_other_document(*, application, uploaded_file, by_user, notes: str = ""):
    """A homeowner-supplied extra document (doc_type=other) with its file in one step."""
    from .documents import validate_upload
    from .models import Document

    validate_upload(uploaded_file)
    with transaction.atomic():
        # Lock the parent row so two concurrent uploads cannot both slip under the cap.
        type(application).objects.select_for_update().get(pk=application.pk)
        from django.conf import settings

        existing = Document.objects.filter(application=application, doc_type=DocumentType.OTHER).count()
        if existing >= settings.MAX_OTHER_DOCUMENTS:
            raise ValidationError(
                {"file": f"This application already has {existing} extra documents (limit {settings.MAX_OTHER_DOCUMENTS})."}
            )
        document = Document(
            application=application,
            doc_type=DocumentType.OTHER,
            status=DocumentStatus.UPLOADED,
            uploaded_by=by_user,
            uploaded_at=timezone.now(),
            notes=notes,
        )
        document.file.save(uploaded_file.name, uploaded_file, save=False)
        document.save()
    return document


__all__ = [
    "AssignmentConflict",
    "DocumentLocked",
    "InvalidTransition",
    "add_note",
    "add_other_document",
    "allowed_transitions",
    "assign_application",
    "claim_application",
    "completion_blockers",
    "review_documents",
    "submit_intake",
    "transition_application",
    "upload_document",
    "validate_application",
    "validate_application_links",
    "validate_ops_user",
    "validate_visit",
    "withdraw_application",
]
