"""
Milestone 3: intake submission (transaction boundary 1), required-document rules,
compliance seeding, and homeowner ownership at queryset + object level.
"""

from unittest import mock

import pytest
from django.urls import reverse

from applications.documents import required_document_types
from applications.enums import ApplicationStatus, ComplianceItemType, ComplianceStatus, DocumentType
from applications.models import Application, ApplicationStatusHistory, ComplianceItem, Document, Property, Suite
from tests.api_helpers import client_for, intake_payload
from tests.factories import ApplicationFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("homeowner-applications")


def detail_url(app_id):
    return reverse("homeowner-application", kwargs={"pk": app_id})


# ---------------------------------------------------------------------------
# Required document rules (pure function)
# ---------------------------------------------------------------------------
class TestRequiredDocuments:
    COMMON = {
        "application_form", "site_plan", "floor_plans", "abandoned_well_declaration",
        "site_contamination_statement", "public_tree_disclosure", "land_title",
    }

    def test_new_suite_modern_home(self):
        assert set(required_document_types("new", 2005)) == self.COMMON | {"elevations"}

    def test_legalize_existing_modern_home(self):
        assert set(required_document_types("legalize_existing", 2005)) == self.COMMON | {"colour_photos"}

    def test_pre_1990_adds_asbestos(self):
        assert "asbestos_abatement" in required_document_types("legalize_existing", 1989)
        assert "asbestos_abatement" in required_document_types("new", 1950)

    def test_1990_exactly_no_asbestos(self):
        assert "asbestos_abatement" not in required_document_types("new", 1990)

    def test_unknown_year_no_asbestos(self):
        assert "asbestos_abatement" not in required_document_types("new", None)

    def test_no_duplicates(self):
        types = required_document_types("legalize_existing", 1950)
        assert len(types) == len(set(types))


# ---------------------------------------------------------------------------
# Intake submit
# ---------------------------------------------------------------------------
class TestIntakeSubmit:
    def test_creates_everything_in_one_call(self, homeowner):
        res = client_for(homeowner).post(LIST_URL, intake_payload(), format="json")
        assert res.status_code == 201, res.data
        data = res.data

        app = Application.objects.get(pk=data["id"])
        assert app.homeowner == homeowner
        assert app.status == ApplicationStatus.INTAKE
        assert app.submitted_at is not None
        assert app.pursuing_incentive is True
        assert app.property.owner == homeowner
        assert app.property.street_address == "1234 17 Ave SW"
        assert app.property.city == "Calgary" and app.property.province == "AB"
        assert app.suite.property == app.property
        assert app.suite.suite_type == "legalize_existing"

        # Compliance: 8 standard + 1 'other' from other_issues
        items = {i.item_type: i for i in app.compliance_items.all()}
        assert len(items) == 9 and ComplianceItemType.OTHER in items
        assert items["egress_window"].status == ComplianceStatus.NEEDS_WORK
        assert items["ceiling_height"].status == ComplianceStatus.COMPLIANT
        assert items["smoke_co_alarms"].status == ComplianceStatus.NOT_ASSESSED
        assert items["fire_separation"].status == ComplianceStatus.NOT_ASSESSED  # unanswered
        assert items["separate_entrance"].status == ComplianceStatus.COMPLIANT  # derived from suite
        assert "Furnace room door" in items["other"].notes

        # Documents: legalize_existing + pre-1990 -> common 7 + colour_photos + asbestos
        doc_types = {d.doc_type for d in app.documents.all()}
        assert doc_types == set(required_document_types("legalize_existing", 1975))
        assert DocumentType.COLOUR_PHOTOS in doc_types and DocumentType.ASBESTOS_ABATEMENT in doc_types
        assert all(d.status == "required" and not d.file for d in app.documents.all())

        # First history row
        hist = list(app.status_history.all())
        assert len(hist) == 1
        assert hist[0].from_status is None and hist[0].to_status == ApplicationStatus.INTAKE
        assert hist[0].changed_by == homeowner
        assert "Financing guidance requested: yes" in hist[0].note
        assert "Want to rent to a student" in hist[0].note

        # Response is the full detail
        assert data["status"] == "intake" and len(data["documents"]) == 9
        assert data["status_history"][0]["changed_by_role"] == "you"

    def test_new_suite_gets_elevations_not_photos(self, homeowner):
        payload = intake_payload(suite={"suite_type": "new"}, property={"year_built": 2010})
        res = client_for(homeowner).post(LIST_URL, payload, format="json")
        assert res.status_code == 201
        doc_types = {d["doc_type"] for d in res.data["documents"]}
        assert "elevations" in doc_types and "colour_photos" not in doc_types and "asbestos_abatement" not in doc_types

    def test_minimal_payload(self, homeowner):
        payload = {
            "property": {"street_address": "1 Main St", "postal_code": "T1A 1A1"},
            "suite": {"suite_type": "new"},
        }
        res = client_for(homeowner).post(LIST_URL, payload, format="json")
        assert res.status_code == 201
        app = Application.objects.get(pk=res.data["id"])
        assert app.compliance_items.count() == 8  # no 'other'
        assert all(i.status == "not_assessed" for i in app.compliance_items.all())
        assert app.pursuing_incentive is False

    def test_atomic_rollback_on_failure(self, homeowner):
        """If seeding documents fails, nothing from the intake survives."""
        before = (Property.objects.count(), Suite.objects.count(), Application.objects.count(),
                  ComplianceItem.objects.count(), ApplicationStatusHistory.objects.count())
        with mock.patch.object(Document.objects, "bulk_create", side_effect=RuntimeError("disk on fire")):
            with pytest.raises(RuntimeError):
                client_for(homeowner).post(LIST_URL, intake_payload(), format="json")
        after = (Property.objects.count(), Suite.objects.count(), Application.objects.count(),
                 ComplianceItem.objects.count(), ApplicationStatusHistory.objects.count())
        assert before == after

    @pytest.mark.parametrize(
        "bad,field",
        [
            ({"compliance": {"egress_window": "na"}}, "compliance"),  # ops-only status
            ({"compliance": {"not_a_thing": "compliant"}}, "compliance"),
            ({"suite": {"suite_type": "duplex"}}, "suite"),
            ({"property": {"year_built": 1700}}, "property"),
            ({"property": {"street_address": ""}}, "property"),
        ],
    )
    def test_validation_errors(self, homeowner, bad, field):
        res = client_for(homeowner).post(LIST_URL, intake_payload(**bad), format="json")
        assert res.status_code == 400 and field in res.data
        assert Application.objects.count() == 0

    def test_client_cannot_set_status_or_homeowner(self, homeowner, other_homeowner):
        payload = intake_payload()
        payload["status"] = "complete"
        payload["homeowner"] = str(other_homeowner.id)
        res = client_for(homeowner).post(LIST_URL, payload, format="json")
        assert res.status_code == 201
        app = Application.objects.get(pk=res.data["id"])
        assert app.status == "intake" and app.homeowner == homeowner

    def test_ops_roles_cannot_submit_intake(self, staff, admin):
        for user in (staff, admin):
            assert client_for(user).post(LIST_URL, intake_payload(), format="json").status_code == 403

    def test_anonymous_rejected(self):
        from rest_framework.test import APIClient

        assert APIClient().post(LIST_URL, intake_payload(), format="json").status_code == 401


# ---------------------------------------------------------------------------
# Ownership: queryset + object level
# ---------------------------------------------------------------------------
class TestOwnership:
    def test_list_shows_only_own(self, homeowner, other_homeowner):
        mine = ApplicationFactory(homeowner=homeowner)
        ApplicationFactory(homeowner=other_homeowner)
        res = client_for(homeowner).get(LIST_URL)
        assert res.status_code == 200
        assert [a["id"] for a in res.data] == [str(mine.id)]

    def test_other_homeowners_application_is_404(self, homeowner, other_homeowner):
        theirs = ApplicationFactory(homeowner=other_homeowner)
        res = client_for(homeowner).get(detail_url(theirs.id))
        assert res.status_code == 404  # not 403: existence is not revealed

    def test_own_application_detail(self, homeowner):
        mine = ApplicationFactory(homeowner=homeowner)
        res = client_for(homeowner).get(detail_url(mine.id))
        assert res.status_code == 200 and res.data["id"] == str(mine.id)
        assert res.data["property"]["street_address"] == mine.property.street_address

    def test_object_permission_is_independent_of_queryset(self, homeowner, other_homeowner):
        """Even if a queryset bug leaked another owner's row, IsApplicationOwner blocks it."""
        from accounts.permissions import IsApplicationOwner

        theirs = ApplicationFactory(homeowner=other_homeowner)
        request = mock.Mock(user=homeowner)
        assert IsApplicationOwner().has_object_permission(request, None, theirs) is False
        mine = ApplicationFactory(homeowner=homeowner)
        assert IsApplicationOwner().has_object_permission(request, None, mine) is True
        # Child rows resolve through their application
        doc = Document.objects.create(application=theirs, doc_type="other")
        assert IsApplicationOwner().has_object_permission(request, None, doc) is False

    def test_history_never_exposes_staff_identity(self, homeowner, staff):
        mine = ApplicationFactory(homeowner=homeowner)
        ApplicationStatusHistory.objects.create(
            application=mine, from_status=None, to_status="intake", changed_by=staff, note="Created by staff"
        )
        res = client_for(homeowner).get(detail_url(mine.id))
        row = res.data["status_history"][0]
        assert row["changed_by_role"] == "ready2rent"
        assert staff.email not in str(res.data)


# ---------------------------------------------------------------------------
# Withdraw (uses the locked transition service)
# ---------------------------------------------------------------------------
class TestWithdraw:
    def test_withdraw_from_intake(self, homeowner):
        res = client_for(homeowner).post(LIST_URL, intake_payload(), format="json")
        app_id = res.data["id"]
        res = client_for(homeowner).post(
            reverse("homeowner-application-withdraw", kwargs={"pk": app_id}), {"note": "Changed my mind"}, format="json"
        )
        assert res.status_code == 200 and res.data["status"] == "withdrawn"
        assert res.data["can_withdraw"] is False
        hist = res.data["status_history"]
        assert hist[-1]["from_status"] == "intake" and hist[-1]["to_status"] == "withdrawn"
        assert hist[-1]["note"] == "Changed my mind"

    def test_cannot_withdraw_twice(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner, status="withdrawn")
        res = client_for(homeowner).post(reverse("homeowner-application-withdraw", kwargs={"pk": app.id}), {}, format="json")
        assert res.status_code == 409
        app.refresh_from_db()
        assert app.status == "withdrawn" and app.status_history.count() == 0

    def test_cannot_withdraw_completed(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner, status="complete")
        res = client_for(homeowner).post(reverse("homeowner-application-withdraw", kwargs={"pk": app.id}), {}, format="json")
        assert res.status_code == 409

    def test_cannot_withdraw_someone_elses(self, homeowner, other_homeowner):
        theirs = ApplicationFactory(homeowner=other_homeowner)
        res = client_for(homeowner).post(reverse("homeowner-application-withdraw", kwargs={"pk": theirs.id}), {}, format="json")
        assert res.status_code == 404
        theirs.refresh_from_db()
        assert theirs.status == "intake"
