"""
Service-layer units not covered elsewhere: the pure helpers, assignment atomicity,
and upload hardening.
"""

import datetime as dt
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from applications.enums import ApplicationStatus as S
from applications.enums import PermitStatus, VisitStatus, VisitType
from applications.models import ApplicationStatusHistory, Document
from applications.services import (
    add_note,
    allowed_transitions,
    assign_application,
    completion_blockers,
    submit_intake,
)
from tests.api_helpers import client_for
from tests.factories import ApplicationFactory, PermitFactory, StatusHistoryFactory, VisitFactory

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.4\n%x\n"


class TestAllowedTransitions:
    @pytest.mark.parametrize(
        "status,expected",
        [
            (S.INTAKE, ["eligibility_check", "withdrawn"]),
            (S.REGISTERED, ["complete"]),
            (S.COMPLETE, []),
            (S.WITHDRAWN, []),
        ],
    )
    def test_from_state_machine(self, status, expected):
        assert allowed_transitions(ApplicationFactory(status=status)) == expected

    def test_on_hold_offers_prior_status_then_withdrawn(self):
        app = ApplicationFactory(status=S.ON_HOLD)
        StatusHistoryFactory(application=app, from_status=S.CONSTRUCTION, to_status=S.ON_HOLD)
        assert allowed_transitions(app) == ["construction", "withdrawn"]

    def test_on_hold_without_history_offers_only_withdrawn(self):
        assert allowed_transitions(ApplicationFactory(status=S.ON_HOLD)) == ["withdrawn"]

    def test_on_hold_uses_latest_hold(self):
        app = ApplicationFactory(status=S.ON_HOLD)
        StatusHistoryFactory(application=app, from_status=S.PERMITS, to_status=S.ON_HOLD)
        StatusHistoryFactory(application=app, from_status=S.ON_HOLD, to_status=S.PERMITS)
        StatusHistoryFactory(application=app, from_status=S.INSPECTIONS, to_status=S.ON_HOLD)
        assert allowed_transitions(app) == ["inspections", "withdrawn"]


class TestCompletionBlockers:
    def test_empty_application_lists_both_gaps(self):
        reasons = completion_blockers(ApplicationFactory())
        assert any("No permits" in r for r in reasons)
        assert any("No inspection" in r for r in reasons)

    def test_not_required_permits_are_ignored(self):
        app = ApplicationFactory()
        PermitFactory(application=app, permit_type="development", status=PermitStatus.NOT_REQUIRED)
        PermitFactory(application=app, permit_type="building", status=PermitStatus.APPROVED)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.COMPLETED)
        assert completion_blockers(app) == []

    @pytest.mark.parametrize("status", [PermitStatus.NOT_STARTED, PermitStatus.APPLIED, PermitStatus.REJECTED, PermitStatus.EXPIRED])
    def test_each_unapproved_permit_status_blocks(self, status):
        app = ApplicationFactory()
        PermitFactory(application=app, permit_type="gas", status=status)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.COMPLETED)
        reasons = completion_blockers(app)
        assert len(reasons) == 1 and "Gas permit" in reasons[0]

    def test_cancelled_and_no_show_inspections_do_not_count_as_open(self):
        app = ApplicationFactory()
        PermitFactory(application=app, permit_type="building", status=PermitStatus.APPROVED)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.CANCELLED)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.NO_SHOW)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.COMPLETED)
        assert completion_blockers(app) == []

    def test_open_inspection_named_with_date(self):
        app = ApplicationFactory()
        PermitFactory(application=app, permit_type="building", status=PermitStatus.APPROVED)
        VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.COMPLETED)
        VisitFactory(
            application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.SCHEDULED,
            scheduled_for=dt.datetime(2026, 11, 3, 10, 0, tzinfo=dt.UTC),
        )
        reasons = completion_blockers(app)
        assert reasons == ["An inspection scheduled for 2026-11-03 is still open."]


class TestAssignmentAtomicity:
    def test_history_failure_rolls_back_assignment(self, admin, staff):
        app = ApplicationFactory()
        with mock.patch.object(ApplicationStatusHistory.objects, "create", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                assign_application(application_id=app.id, staff=staff, by_user=admin)
        app.refresh_from_db()
        assert app.assigned_staff is None

    def test_unassign_records_previous_owner(self, admin, staff):
        app = ApplicationFactory(assigned_staff=staff)
        assign_application(application_id=app.id, staff=None, by_user=admin)
        note = app.status_history.get().note
        assert "nobody (unassigned)" in note and (staff.get_full_name() or staff.email) in note

    def test_note_rejects_blank(self, admin):
        app = ApplicationFactory()
        with pytest.raises(ValidationError):
            add_note(application_id=app.id, by_user=admin, note="  \n ")
        assert app.status_history.count() == 0


class TestIntakeServiceGuards:
    def test_service_rejects_na_self_report_even_when_called_directly(self, homeowner):
        with pytest.raises(ValidationError):
            submit_intake(
                homeowner=homeowner,
                property_data={"street_address": "1 A St", "postal_code": "T1A1A1"},
                suite_data={"suite_type": "new"},
                compliance={"parking": "na"},
            )

    def test_service_rejects_unknown_item(self, homeowner):
        with pytest.raises(ValidationError):
            submit_intake(
                homeowner=homeowner,
                property_data={"street_address": "1 A St", "postal_code": "T1A1A1"},
                suite_data={"suite_type": "new"},
                compliance={"hot_tub": "compliant"},
            )


class TestUploadHardening:
    @pytest.fixture(autouse=True)
    def media_tmp(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path / "media"

    def test_path_traversal_in_filename_is_neutralised(self, homeowner, settings):
        app = ApplicationFactory(homeowner=homeowner)
        doc = Document.objects.create(application=app, doc_type="site_plan")
        evil = SimpleUploadedFile("..\\..\\..\\evil.pdf", PDF)
        res = client_for(homeowner).post(
            reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}), {"file": evil}, format="multipart"
        )
        assert res.status_code == 200
        doc.refresh_from_db()
        stored = (settings.MEDIA_ROOT / doc.file.name).resolve()
        assert str(stored).startswith(str(settings.MEDIA_ROOT.resolve()))
        assert ".." not in doc.file.name
        assert doc.file.name.startswith(f"applications/{app.id}/site_plan/")

    def test_other_document_type_is_forced(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        res = client_for(homeowner).post(
            reverse("homeowner-document-create", kwargs={"pk": app.id}),
            {"file": SimpleUploadedFile("x.pdf", PDF), "doc_type": "land_title", "status": "accepted"},
            format="multipart",
        )
        assert res.status_code == 201
        assert res.data["doc_type"] == "other" and res.data["status"] == "uploaded"
