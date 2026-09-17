"""
Cross-table rules that PostgreSQL cannot enforce, proven on BOTH code paths:
  - full_clean()  (admin / forms)
  - save()        (any ORM write, including service code)
"""

import pytest
from django.core.exceptions import ValidationError

from accounts.models import UserRole
from applications.models import Application, Visit
from applications.services import validate_ops_user
from tests.factories import ApplicationFactory, PropertyFactory, SuiteFactory, UserFactory, VisitFactory

pytestmark = pytest.mark.django_db


class TestApplicationOwnershipRules:
    def test_property_must_belong_to_homeowner__save(self, homeowner, other_homeowner):
        foreign_prop = PropertyFactory(owner=other_homeowner)
        suite = SuiteFactory(property=foreign_prop)
        with pytest.raises(ValidationError) as exc:
            Application.objects.create(homeowner=homeowner, property=foreign_prop, suite=suite)
        assert "property" in exc.value.message_dict

    def test_property_must_belong_to_homeowner__clean(self, homeowner, other_homeowner):
        foreign_prop = PropertyFactory(owner=other_homeowner)
        suite = SuiteFactory(property=foreign_prop)
        app = Application(homeowner=homeowner, property=foreign_prop, suite=suite)
        with pytest.raises(ValidationError) as exc:
            app.full_clean()
        assert "property" in exc.value.message_dict

    def test_suite_must_belong_to_property__save(self, homeowner, prop):
        other_prop = PropertyFactory(owner=homeowner)
        stray_suite = SuiteFactory(property=other_prop)
        with pytest.raises(ValidationError) as exc:
            Application.objects.create(homeowner=homeowner, property=prop, suite=stray_suite)
        assert "suite" in exc.value.message_dict

    def test_suite_must_belong_to_property__clean(self, homeowner, prop):
        other_prop = PropertyFactory(owner=homeowner)
        stray_suite = SuiteFactory(property=other_prop)
        app = Application(homeowner=homeowner, property=prop, suite=stray_suite)
        with pytest.raises(ValidationError) as exc:
            app.full_clean()
        assert "suite" in exc.value.message_dict

    def test_consistent_application_saves(self, homeowner, prop, suite):
        app = Application.objects.create(homeowner=homeowner, property=prop, suite=suite)
        app.full_clean()  # no exception
        assert app.pk

    def test_update_that_breaks_ownership_is_rejected(self, application, other_homeowner):
        application.homeowner = other_homeowner
        with pytest.raises(ValidationError):
            application.save()
        application.refresh_from_db()
        assert application.homeowner_id != other_homeowner.id


class TestAssignedStaffRole:
    @pytest.mark.parametrize("role", [UserRole.STAFF, UserRole.ADMIN])
    def test_ops_roles_accepted(self, application, role):
        application.assigned_staff = UserFactory(role=role)
        application.save()
        application.full_clean()

    def test_homeowner_rejected_on_save(self, application, other_homeowner):
        application.assigned_staff = other_homeowner
        with pytest.raises(ValidationError) as exc:
            application.save()
        assert "assigned_staff" in exc.value.message_dict

    def test_homeowner_rejected_on_clean(self, application, other_homeowner):
        application.assigned_staff = other_homeowner
        with pytest.raises(ValidationError) as exc:
            application.full_clean()
        assert "assigned_staff" in exc.value.message_dict

    def test_unassigned_is_fine(self, application):
        application.assigned_staff = None
        application.save()

    def test_visit_assigned_staff_must_be_ops(self, application, other_homeowner, staff):
        with pytest.raises(ValidationError):
            VisitFactory(application=application, assigned_staff=other_homeowner)
        v = VisitFactory(application=application, assigned_staff=staff)
        v.full_clean()
        assert Visit.objects.filter(pk=v.pk).exists()

    def test_validate_ops_user_helper(self, homeowner, staff, admin):
        validate_ops_user(None)
        validate_ops_user(staff)
        validate_ops_user(admin)
        with pytest.raises(ValidationError):
            validate_ops_user(homeowner)


class TestFactoriesAreConsistent:
    def test_default_application_factory_passes_all_rules(self):
        app = ApplicationFactory()
        app.full_clean()
        assert app.property.owner_id == app.homeowner_id
        assert app.suite.property_id == app.property_id
