"""
Domain models, implemented 1:1 from docs/schema.md.

on_delete policy (schema "Relationships & on_delete rationale"):
  - Application children -> CASCADE (meaningless without their application)
  - homeowner / property / suite on Application -> PROTECT
  - assigned_staff / uploaded_by -> SET_NULL
  - changed_by on history -> PROTECT
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from core.models import CreatedModel, TimeStampedModel

from . import services
from .enums import (
    ApplicationStatus,
    ComplianceItemType,
    ComplianceStatus,
    DocumentStatus,
    DocumentType,
    PermitStatus,
    PermitType,
    SuiteType,
    VisitStatus,
    VisitType,
)

# Reused on every FK that must point at an ops user. A DB-level guarantee is not
# possible across tables, so the service layer + admin also validate the role.
_OPS_ROLES = Q(role__in=["staff", "admin"])


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
class Property(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="properties"
    )
    street_address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, default="Calgary")
    province = models.CharField(max_length=2, default="AB")
    postal_code = models.CharField(max_length=10)
    # Set during eligibility check; drives whether a Development Permit is required.
    land_use_district = models.CharField(max_length=50, null=True, blank=True)
    # < 1990 triggers a required asbestos_abatement document.
    year_built = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "properties"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(year_built__isnull=True) | Q(year_built__gte=1800, year_built__lte=2100),
                name="property_year_built_reasonable",
            ),
        ]

    def __str__(self):
        return f"{self.street_address}, {self.city}"

    @property
    def requires_asbestos_form(self) -> bool:
        return self.year_built is not None and self.year_built < 1990


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------
class Suite(TimeStampedModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="suites")
    suite_type = models.CharField(max_length=20, choices=SuiteType.choices)
    has_separate_entrance = models.BooleanField(null=True, blank=True)  # unknown during intake
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_suite_type_display()} @ {self.property}"


# ---------------------------------------------------------------------------
# Application (the "lead")
# ---------------------------------------------------------------------------
class Application(TimeStampedModel):
    homeowner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="applications"
    )
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="applications")
    suite = models.OneToOneField(Suite, on_delete=models.PROTECT, related_name="application")
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_applications",
        limit_choices_to=_OPS_ROLES,
    )
    status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.INTAKE, db_index=True
    )
    pursuing_incentive = models.BooleanField(default=False)  # program winding down
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Ops queue: filter by status, newest first. (FK columns are indexed automatically.)
            models.Index(fields=["status", "-created_at"], name="application_queue_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(estimated_cost__isnull=True) | Q(estimated_cost__gte=0),
                name="application_cost_non_negative",
            ),
        ]

    def __str__(self):
        return f"Application {str(self.id)[:8]} ({self.get_status_display()})"

    # Cross-table rules (homeowner owns property, suite belongs to property,
    # assigned_staff is staff/admin) cannot be DB constraints. They are enforced
    # on every ORM save AND in clean() so admin, services, and raw saves all agree.
    def clean(self):
        super().clean()
        services.validate_application(self)

    def save(self, *args, **kwargs):
        services.validate_application(self)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# ApplicationStatusHistory (append-only)
# ---------------------------------------------------------------------------
class ApplicationStatusHistory(CreatedModel):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices, null=True, blank=True  # null on first row
    )
    to_status = models.CharField(max_length=20, choices=ApplicationStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "application status history"
        ordering = ["created_at"]
        # created_at already indexed via CreatedModel; application FK indexed automatically.

    def __str__(self):
        return f"{self.from_status or '∅'} → {self.to_status}"

    # Append-only enforcement at the ORM level. (Bulk .update()/.delete() querysets
    # bypass this, which is why the service layer never exposes them for this model.)
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Status history rows are append-only and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Status history rows are append-only and cannot be deleted.")


# ---------------------------------------------------------------------------
# ComplianceItem
# ---------------------------------------------------------------------------
class ComplianceItem(TimeStampedModel):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="compliance_items"
    )
    item_type = models.CharField(max_length=30, choices=ComplianceItemType.choices)
    status = models.CharField(
        max_length=20, choices=ComplianceStatus.choices, default=ComplianceStatus.NOT_ASSESSED
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["item_type"]
        constraints = [
            # One row per standard item; any number of 'other' rows.
            models.UniqueConstraint(
                fields=["application", "item_type"],
                condition=~Q(item_type=ComplianceItemType.OTHER),
                name="compliance_item_unique_per_application",
            ),
        ]

    def __str__(self):
        return f"{self.get_item_type_display()}: {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------
class Permit(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="permits")
    permit_type = models.CharField(max_length=20, choices=PermitType.choices)
    permit_number = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=PermitStatus.choices, default=PermitStatus.NOT_STARTED
    )
    applied_date = models.DateField(null=True, blank=True)
    approved_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["permit_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "permit_type"], name="permit_unique_per_application"
            ),
            models.CheckConstraint(
                condition=Q(approved_date__isnull=True)
                | Q(applied_date__isnull=True)
                | Q(approved_date__gte=F("applied_date")),
                name="permit_approved_not_before_applied",
            ),
        ]

    def __str__(self):
        return f"{self.get_permit_type_display()}: {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
def document_upload_path(instance, filename: str) -> str:
    # media/applications/<application uuid>/<doc_type>/<original filename>
    return f"applications/{instance.application_id}/{instance.doc_type}/{filename}"


class Document(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=40, choices=DocumentType.choices)
    file = models.FileField(upload_to=document_upload_path, null=True, blank=True)  # null until uploaded
    status = models.CharField(
        max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.REQUIRED
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["doc_type"]
        constraints = [
            # A document cannot be 'uploaded'/'accepted'/'rejected' without a file behind it.
            models.CheckConstraint(
                condition=Q(status=DocumentStatus.REQUIRED) | (Q(file__isnull=False) & ~Q(file="")),
                name="document_file_present_unless_required",
            ),
        ]

    def __str__(self):
        return f"{self.get_doc_type_display()}: {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Visit
# ---------------------------------------------------------------------------
class Visit(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="visits")
    visit_type = models.CharField(max_length=20, choices=VisitType.choices)
    scheduled_for = models.DateTimeField(db_index=True)
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_visits",
        limit_choices_to=_OPS_ROLES,
    )
    status = models.CharField(max_length=20, choices=VisitStatus.choices, default=VisitStatus.SCHEDULED)
    outcome_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["scheduled_for"]

    def __str__(self):
        return f"{self.get_visit_type_display()} on {self.scheduled_for:%Y-%m-%d %H:%M}"

    def clean(self):
        super().clean()
        services.validate_visit(self)

    def save(self, *args, **kwargs):
        services.validate_visit(self)
        super().save(*args, **kwargs)
