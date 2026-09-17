"""on_delete policy from docs/schema.md, exercised against PostgreSQL."""

import pytest
from django.db.models import ProtectedError

from applications.models import Application, ComplianceItem, Document, Permit, Suite, Visit
from tests.factories import (
    ComplianceItemFactory,
    DocumentFactory,
    PermitFactory,
    StatusHistoryFactory,
    UserFactory,
    VisitFactory,
)

pytestmark = pytest.mark.django_db


class TestProtect:
    def test_cannot_delete_homeowner_with_application(self, application):
        with pytest.raises(ProtectedError):
            application.homeowner.delete()

    def test_cannot_delete_property_with_application(self, application):
        with pytest.raises(ProtectedError):
            application.property.delete()

    def test_cannot_delete_suite_with_application(self, application):
        with pytest.raises(ProtectedError):
            application.suite.delete()

    def test_cannot_delete_owner_with_property(self, prop):
        with pytest.raises(ProtectedError):
            prop.owner.delete()


class TestCascade:
    def test_deleting_application_removes_children(self, application, staff):
        StatusHistoryFactory(application=application)
        ComplianceItemFactory(application=application)
        PermitFactory(application=application)
        DocumentFactory(application=application)
        VisitFactory(application=application, assigned_staff=staff)
        app_id = application.pk

        # CASCADE is part of the approved schema: deleting an application removes its
        # history too. Django's collector deletes children in bulk (it does not call
        # the child's Model.delete()), so the append-only guard does not block this.
        application.delete()

        from applications.models import ApplicationStatusHistory

        assert not ApplicationStatusHistory.objects.filter(application_id=app_id).exists()
        assert not ComplianceItem.objects.filter(application_id=app_id).exists()
        assert not Permit.objects.filter(application_id=app_id).exists()
        assert not Document.objects.filter(application_id=app_id).exists()
        assert not Visit.objects.filter(application_id=app_id).exists()

    def test_deleting_property_removes_suites(self, homeowner):
        from tests.factories import PropertyFactory, SuiteFactory

        p = PropertyFactory(owner=homeowner)
        s = SuiteFactory(property=p)
        p.delete()
        assert not Suite.objects.filter(pk=s.pk).exists()


class TestSetNull:
    def test_deleting_assigned_staff_nulls_pointer(self, application):
        staff = UserFactory(role="staff")
        application.assigned_staff = staff
        application.save()
        staff.delete()
        application.refresh_from_db()
        assert application.assigned_staff is None
        assert Application.objects.filter(pk=application.pk).exists()

    def test_deleting_uploader_keeps_document(self, application):
        staff = UserFactory(role="staff")
        doc = DocumentFactory(application=application, uploaded_by=staff)
        staff.delete()
        doc.refresh_from_db()
        assert doc.uploaded_by is None

    def test_deleting_visit_staff_keeps_visit(self, application):
        staff = UserFactory(role="staff")
        visit = VisitFactory(application=application, assigned_staff=staff)
        staff.delete()
        visit.refresh_from_db()
        assert visit.assigned_staff is None
