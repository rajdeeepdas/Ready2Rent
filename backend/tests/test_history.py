"""ApplicationStatusHistory is append-only at the ORM level."""

import pytest
from django.core.exceptions import ValidationError

from applications.enums import ApplicationStatus
from applications.models import ApplicationStatusHistory
from tests.factories import StatusHistoryFactory

pytestmark = pytest.mark.django_db


def test_first_row_may_have_null_from_status(application):
    row = StatusHistoryFactory(application=application, from_status=None, to_status=ApplicationStatus.INTAKE)
    assert row.from_status is None


def test_rows_cannot_be_updated(application):
    row = StatusHistoryFactory(application=application)
    row.note = "tampered"
    with pytest.raises(ValidationError):
        row.save()
    row.refresh_from_db()
    assert row.note == ""


def test_rows_cannot_be_deleted(application):
    row = StatusHistoryFactory(application=application)
    with pytest.raises(ValidationError):
        row.delete()
    assert ApplicationStatusHistory.objects.filter(pk=row.pk).exists()


def test_rows_ordered_oldest_first(application):
    a = StatusHistoryFactory(application=application, to_status=ApplicationStatus.INTAKE)
    b = StatusHistoryFactory(
        application=application,
        from_status=ApplicationStatus.INTAKE,
        to_status=ApplicationStatus.ELIGIBILITY_CHECK,
    )
    assert list(application.status_history.all()) == [a, b]


def test_changed_by_is_protected(application):
    """Deleting the user who made a change must fail (PROTECT)."""
    from django.db.models import ProtectedError

    row = StatusHistoryFactory(application=application, changed_by=application.homeowner)
    with pytest.raises(ProtectedError):
        row.changed_by.delete()
