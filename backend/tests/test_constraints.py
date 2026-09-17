"""
Database-level constraints: the four approved CHECK constraints (null cases and
boundaries) and the two UNIQUE constraints from the spec. These hit PostgreSQL
directly via .save() / .update() so they prove the constraint, not Python code.
"""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from applications.enums import ComplianceItemType, DocumentStatus, PermitType
from applications.models import Application, ComplianceItem, Document, Permit, Property
from tests.factories import ComplianceItemFactory, DocumentFactory, PermitFactory, PropertyFactory

pytestmark = pytest.mark.django_db


def _violates(model_cls, **fields):
    """Raise IntegrityError from a bulk .update() (bypasses Python validation)."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            model_cls.objects.update(**fields)


# ---- property_year_built_reasonable -----------------------------------------
class TestYearBuiltConstraint:
    def test_null_allowed(self, homeowner):
        assert PropertyFactory(owner=homeowner, year_built=None).year_built is None

    @pytest.mark.parametrize("year", [1800, 1989, 1990, 2100])
    def test_boundaries_allowed(self, homeowner, year):
        assert PropertyFactory(owner=homeowner, year_built=year).year_built == year

    @pytest.mark.parametrize("year", [1799, 2101])
    def test_out_of_range_rejected(self, prop, year):
        _violates(Property, year_built=year)

    def test_asbestos_helper_boundary(self, homeowner):
        assert PropertyFactory(owner=homeowner, year_built=1989).requires_asbestos_form is True
        assert PropertyFactory(owner=homeowner, year_built=1990).requires_asbestos_form is False
        assert PropertyFactory(owner=homeowner, year_built=None).requires_asbestos_form is False


# ---- application_cost_non_negative ------------------------------------------
class TestEstimatedCostConstraint:
    def test_null_allowed(self, application):
        assert application.estimated_cost is None

    @pytest.mark.parametrize("cost", [Decimal("0.00"), Decimal("0.01"), Decimal("99999999.99")])
    def test_zero_and_positive_allowed(self, application, cost):
        Application.objects.filter(pk=application.pk).update(estimated_cost=cost)
        application.refresh_from_db()
        assert application.estimated_cost == cost

    def test_negative_rejected(self, application):
        _violates(Application, estimated_cost=Decimal("-0.01"))


# ---- permit_approved_not_before_applied -------------------------------------
class TestPermitDateConstraint:
    def test_both_null_allowed(self, application):
        p = PermitFactory(application=application)
        assert p.applied_date is None and p.approved_date is None

    def test_only_applied_allowed(self, application):
        PermitFactory(application=application, applied_date=dt.date(2026, 1, 1))

    def test_only_approved_allowed(self, application):
        PermitFactory(application=application, approved_date=dt.date(2026, 1, 1))

    def test_same_day_allowed(self, application):
        d = dt.date(2026, 3, 1)
        PermitFactory(application=application, applied_date=d, approved_date=d)

    def test_approved_after_applied_allowed(self, application):
        PermitFactory(
            application=application,
            applied_date=dt.date(2026, 3, 1),
            approved_date=dt.date(2026, 3, 2),
        )

    def test_approved_before_applied_rejected(self, application):
        PermitFactory(application=application, applied_date=dt.date(2026, 3, 2))
        _violates(Permit, approved_date=dt.date(2026, 3, 1))


# ---- document_file_present_unless_required ----------------------------------
class TestDocumentFileConstraint:
    def test_required_without_file_allowed(self, application):
        d = DocumentFactory(application=application)
        assert d.status == DocumentStatus.REQUIRED and not d.file

    @pytest.mark.parametrize(
        "status", [DocumentStatus.UPLOADED, DocumentStatus.ACCEPTED, DocumentStatus.REJECTED]
    )
    def test_non_required_status_without_file_rejected(self, application, status):
        DocumentFactory(application=application)
        _violates(Document, status=status)

    @pytest.mark.parametrize(
        "status", [DocumentStatus.UPLOADED, DocumentStatus.ACCEPTED, DocumentStatus.REJECTED]
    )
    def test_non_required_status_with_file_allowed(self, application, status, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        d = DocumentFactory(application=application)
        d.file.save("plan.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        d.status = status
        d.save()
        d.refresh_from_db()
        assert d.status == status and d.file.name.endswith("plan.pdf")


# ---- UNIQUE constraints -----------------------------------------------------
class TestUniqueConstraints:
    def test_compliance_item_unique_per_application(self, application):
        ComplianceItemFactory(application=application, item_type=ComplianceItemType.PARKING)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ComplianceItemFactory(application=application, item_type=ComplianceItemType.PARKING)

    def test_compliance_item_other_may_repeat(self, application):
        ComplianceItemFactory(application=application, item_type=ComplianceItemType.OTHER, notes="a")
        ComplianceItemFactory(application=application, item_type=ComplianceItemType.OTHER, notes="b")
        assert ComplianceItem.objects.filter(application=application).count() == 2

    def test_same_item_type_allowed_on_different_applications(self, application):
        from tests.factories import ApplicationFactory

        other = ApplicationFactory()
        ComplianceItemFactory(application=application, item_type=ComplianceItemType.PARKING)
        ComplianceItemFactory(application=other, item_type=ComplianceItemType.PARKING)

    def test_permit_unique_per_application(self, application):
        PermitFactory(application=application, permit_type=PermitType.GAS)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PermitFactory(application=application, permit_type=PermitType.GAS)

    def test_suite_one_to_one_with_application(self, application):
        from tests.factories import ApplicationFactory

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ApplicationFactory(
                    homeowner=application.homeowner,
                    property=application.property,
                    suite=application.suite,
                )

    def test_user_email_unique(self, homeowner):
        from tests.factories import UserFactory

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UserFactory(email=homeowner.email)
