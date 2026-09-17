"""
Celery tasks: notifications. All are idempotent and safe to retry: they re-read the
application by id, so a stale or deleted id simply results in no email.

Locally EMAIL_BACKEND is the console backend, so messages print in the worker terminal.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from accounts.models import User, UserRole

logger = logging.getLogger(__name__)

RETRY = dict(autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, max_retries=3, acks_late=True)


def _subject(text: str, limit: int = 150) -> str:
    """Homeowner-typed text (street address) goes into subjects. Collapse all whitespace so a
    line break cannot break or inject email headers, and cap the length."""
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _ops_recipients(application=None) -> list[str]:
    """Assigned staff if any, otherwise every active staff/admin."""
    if application is not None and application.assigned_staff and application.assigned_staff.is_active:
        return [application.assigned_staff.email]
    return list(
        User.objects.filter(role__in=[UserRole.STAFF, UserRole.ADMIN], is_active=True).values_list("email", flat=True)
    )


def _load(application_id):
    from .models import Application

    return (
        Application.objects.select_related("homeowner", "property", "suite", "assigned_staff")
        .filter(pk=application_id)
        .first()
    )


@shared_task(name="applications.notify_staff_new_lead", **RETRY)
def notify_staff_new_lead(application_id: str) -> int:
    app = _load(application_id)
    if app is None:
        logger.info("notify_staff_new_lead: application %s no longer exists", application_id)
        return 0
    recipients = _ops_recipients()
    if not recipients:
        logger.warning("notify_staff_new_lead: no active ops users to notify")
        return 0
    subject = _subject(f"[Ready2Rent] New lead: {app.property.street_address}")
    body = (
        f"A new application was submitted.\n\n"
        f"Homeowner: {app.homeowner.get_full_name() or app.homeowner.email} <{app.homeowner.email}>\n"
        f"Property:  {app.property.street_address}, {app.property.city} {app.property.postal_code}\n"
        f"Path:      {app.suite.get_suite_type_display()}\n"
        f"Incentive: {'yes' if app.pursuing_incentive else 'no'}\n\n"
        f"Open it in the ops queue: {settings.FRONTEND_URL}/ops/applications/{app.id}\n"
    )
    return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)


@shared_task(name="applications.email_homeowner_status_change", **RETRY)
def email_homeowner_status_change(application_id: str, from_status: str | None, to_status: str, note: str = "") -> int:
    from .enums import ApplicationStatus

    app = _load(application_id)
    if app is None or not app.homeowner.is_active:
        return 0
    label = dict(ApplicationStatus.choices).get(to_status, to_status)
    first = app.homeowner.first_name or "there"
    lines = [
        f"Hi {first},",
        "",
        f"Your application for {app.property.street_address} has moved to: {label}.",
    ]
    if to_status == ApplicationStatus.ON_HOLD:
        lines.append("Our team has paused work on it for now; we will be in touch with the reason.")
    elif to_status == ApplicationStatus.WITHDRAWN:
        lines.append("It has been withdrawn. If this was a mistake, reply to this email.")
    elif to_status == ApplicationStatus.REGISTERED:
        lines.append("Congratulations: your suite has been inspected and registered with the City.")
    if note:
        lines += ["", f"Note from our team: {note}"]
    lines += ["", f"Track it here: {settings.FRONTEND_URL}/app/applications/{app.id}", "", "Ready2Rent"]
    return send_mail(_subject(f"[Ready2Rent] Update: {label}"), "\n".join(lines), settings.DEFAULT_FROM_EMAIL, [app.homeowner.email])


@shared_task(name="applications.notify_staff_homeowner_action", **RETRY)
def notify_staff_homeowner_action(application_id: str, action: str) -> int:
    """A homeowner did something staff should see (withdrew, uploaded). Goes to the
    assigned staff member, or to all ops if unassigned."""
    app = _load(application_id)
    if app is None:
        return 0
    recipients = _ops_recipients(app)
    if not recipients:
        return 0
    subject = _subject(f"[Ready2Rent] {action}: {app.property.street_address}")
    body = (
        f"{app.homeowner.get_full_name() or app.homeowner.email}: {action}.\n\n"
        f"{settings.FRONTEND_URL}/ops/applications/{app.id}\n"
    )
    return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)


@shared_task(name="applications.email_homeowner_documents_reviewed", **RETRY)
def email_homeowner_documents_reviewed(application_id: str, decisions: list[dict]) -> int:
    from .enums import DocumentType

    app = _load(application_id)
    if app is None or not app.homeowner.is_active or not decisions:
        return 0
    labels = dict(DocumentType.choices)
    accepted = [labels.get(d["doc_type"], d["doc_type"]) for d in decisions if d["status"] == "accepted"]
    rejected = [d for d in decisions if d["status"] == "rejected"]
    lines = [f"Hi {app.homeowner.first_name or 'there'},", "", f"We reviewed documents for {app.property.street_address}."]
    if accepted:
        lines += ["", "Accepted:"] + [f"  - {a}" for a in accepted]
    if rejected:
        lines += ["", "Needs another upload:"] + [
            f"  - {labels.get(d['doc_type'], d['doc_type'])}: {d.get('notes') or 'see notes'}" for d in rejected
        ]
    lines += ["", f"Upload or review here: {settings.FRONTEND_URL}/app/applications/{app.id}", "", "Ready2Rent"]
    return send_mail("[Ready2Rent] Document review", "\n".join(lines), settings.DEFAULT_FROM_EMAIL, [app.homeowner.email])
