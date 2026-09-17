"""
Milestone 4: ops queue, access rules (read all / act on assigned / admin any), claim and
assignment under row locks, transitions with completion gating, child editing, and the
atomic bulk document review.
"""

import datetime as dt
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from applications.enums import ApplicationStatus as S
from applications.enums import DocumentStatus, PermitStatus, VisitStatus, VisitType
from applications.models import ApplicationStatusHistory, ComplianceItem, Document, Permit, Visit
from tests.api_helpers import client_for, intake_payload
from tests.factories import (
    ApplicationFactory,
    DocumentFactory,
    PermitFactory,
    UserFactory,
    VisitFactory,
)

pytestmark = pytest.mark.django_db

QUEUE = reverse("ops-queue")
PDF = b"%PDF-1.4\n%x\n"


def u(name, pk, **kw):
    return reverse(name, kwargs={"pk": pk, **kw})


@pytest.fixture
def staff2(db):
    return UserFactory(role="staff")


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def uploaded_doc(application, doc_type="site_plan"):
    doc = DocumentFactory(application=application, doc_type=doc_type)
    doc.file.save("f.pdf", SimpleUploadedFile("f.pdf", PDF), save=False)
    doc.status = DocumentStatus.UPLOADED
    doc.save()
    return doc


# ---------------------------------------------------------------------------
# Surface access
# ---------------------------------------------------------------------------
class TestSurfaceAccess:
    @pytest.mark.parametrize(
        "name,kwargs,method",
        [
            ("ops-queue", {}, "get"),
            ("ops-queue-summary", {}, "get"),
            ("ops-staff", {}, "get"),
            ("ops-options", {}, "get"),
        ],
    )
    def test_homeowner_gets_403_on_ops_urls(self, homeowner, name, kwargs, method):
        res = getattr(client_for(homeowner), method)(reverse(name, kwargs=kwargs))
        assert res.status_code == 403

    def test_homeowner_gets_403_on_ops_application(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)  # even their own
        c = client_for(homeowner)
        assert c.get(u("ops-application", app.id)).status_code == 403
        assert c.post(u("ops-transition", app.id), {"to_status": "eligibility_check"}, format="json").status_code == 403
        assert c.post(u("ops-claim", app.id), {}, format="json").status_code == 403

    def test_anonymous_401(self):
        from rest_framework.test import APIClient

        assert APIClient().get(QUEUE).status_code == 401


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
class TestQueue:
    def test_staff_read_all_applications(self, staff, homeowner, other_homeowner):
        a = ApplicationFactory(homeowner=homeowner)
        b = ApplicationFactory(homeowner=other_homeowner)
        res = client_for(staff).get(QUEUE)
        assert res.status_code == 200
        ids = {row["id"] for row in res.data["results"]}
        assert ids == {str(a.id), str(b.id)}
        assert res.data["count"] == 2
        row = next(r for r in res.data["results"] if r["id"] == str(a.id))
        assert row["homeowner"]["email"] == homeowner.email  # ops see contact info
        assert row["street_address"] == a.property.street_address

    def test_default_hides_closed(self, staff):
        ApplicationFactory(status=S.COMPLETE)
        ApplicationFactory(status=S.WITHDRAWN)
        open_ = ApplicationFactory(status=S.PERMITS)
        res = client_for(staff).get(QUEUE)
        assert [r["id"] for r in res.data["results"]] == [str(open_.id)]
        assert client_for(staff).get(QUEUE, {"status": "all"}).data["count"] == 3
        assert client_for(staff).get(QUEUE, {"status": "complete"}).data["count"] == 1
        assert client_for(staff).get(QUEUE, {"status": "complete,withdrawn"}).data["count"] == 2

    def test_assigned_filters(self, staff, staff2):
        mine = ApplicationFactory(assigned_staff=staff)
        theirs = ApplicationFactory(assigned_staff=staff2)
        nobody = ApplicationFactory()
        c = client_for(staff)
        assert [r["id"] for r in c.get(QUEUE, {"assigned": "me"}).data["results"]] == [str(mine.id)]
        assert [r["id"] for r in c.get(QUEUE, {"assigned": "unassigned"}).data["results"]] == [str(nobody.id)]
        assert [r["id"] for r in c.get(QUEUE, {"assigned": str(staff2.id)}).data["results"]] == [str(theirs.id)]

    def test_search_and_suite_filter(self, staff, homeowner):
        a = ApplicationFactory(homeowner=homeowner)
        a.property.street_address = "77 Unique Crescent NW"
        a.property.save()
        ApplicationFactory()
        c = client_for(staff)
        assert c.get(QUEUE, {"q": "unique crescent"}).data["count"] == 1
        assert c.get(QUEUE, {"q": homeowner.email[:8]}).data["count"] == 1
        assert c.get(QUEUE, {"suite_type": "new"}).data["count"] == 0

    def test_counts_annotated(self, staff, homeowner):
        res = client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
        app_id = res.data["id"]
        doc = Document.objects.get(application_id=app_id, doc_type="site_plan")
        doc.file.save("f.pdf", SimpleUploadedFile("f.pdf", PDF), save=False)
        doc.status = DocumentStatus.UPLOADED
        doc.save()
        row = client_for(staff).get(QUEUE).data["results"][0]
        assert row["docs_pending_review"] == 1
        assert row["docs_required"] == 9 and row["docs_uploaded"] == 1
        assert row["items_needing_work"] == 2  # egress_window + 'other'

    def test_ordering_and_pagination(self, staff, settings):
        for _ in range(3):
            ApplicationFactory()
        res = client_for(staff).get(QUEUE, {"ordering": "created_at"})
        created = [r["submitted_at"] or r["updated_at"] for r in res.data["results"]]
        assert len(created) == 3
        assert "next" in res.data and "previous" in res.data

    def test_summary(self, staff):
        ApplicationFactory(status=S.INTAKE, assigned_staff=staff)
        ApplicationFactory(status=S.INTAKE)
        ApplicationFactory(status=S.COMPLETE)
        res = client_for(staff).get(reverse("ops-queue-summary"))
        assert res.status_code == 200
        assert res.data["by_status"]["intake"] == 2 and res.data["by_status"]["complete"] == 1
        assert res.data["open"] == 2 and res.data["mine"] == 1 and res.data["unassigned"] == 1

    def test_staff_list(self, staff, admin, homeowner):
        res = client_for(staff).get(reverse("ops-staff"))
        emails = {r["email"] for r in res.data}
        assert staff.email in emails and admin.email in emails and homeowner.email not in emails


# ---------------------------------------------------------------------------
# Claim / assign
# ---------------------------------------------------------------------------
class TestClaimAndAssign:
    def test_staff_claims_unassigned(self, staff):
        app = ApplicationFactory()
        res = client_for(staff).post(u("ops-claim", app.id), {}, format="json")
        assert res.status_code == 200
        assert res.data["assigned_staff"]["id"] == str(staff.id)
        assert res.data["can_act"] is True
        app.refresh_from_db()
        assert app.assigned_staff == staff
        note = app.status_history.get()
        assert note.from_status == note.to_status == app.status and "Claimed by" in note.note

    def test_cannot_claim_assigned(self, staff, staff2):
        app = ApplicationFactory(assigned_staff=staff2)
        res = client_for(staff).post(u("ops-claim", app.id), {}, format="json")
        assert res.status_code == 409
        app.refresh_from_db()
        assert app.assigned_staff == staff2 and app.status_history.count() == 0

    def test_staff_cannot_assign_others(self, staff, staff2):
        app = ApplicationFactory()
        res = client_for(staff).post(u("ops-assign", app.id), {"staff_id": str(staff2.id)}, format="json")
        assert res.status_code == 403
        app.refresh_from_db()
        assert app.assigned_staff is None

    def test_admin_assigns_reassigns_unassigns(self, admin, staff, staff2):
        app = ApplicationFactory()
        c = client_for(admin)
        res = c.post(u("ops-assign", app.id), {"staff_id": str(staff.id), "note": "Please take this one"}, format="json")
        assert res.status_code == 200 and res.data["assigned_staff"]["id"] == str(staff.id)
        res = c.post(u("ops-assign", app.id), {"staff_id": str(staff2.id)}, format="json")
        assert res.status_code == 200 and res.data["assigned_staff"]["id"] == str(staff2.id)
        res = c.post(u("ops-assign", app.id), {"staff_id": None}, format="json")
        assert res.status_code == 200 and res.data["assigned_staff"] is None
        notes = [h.note for h in app.status_history.all()]
        assert len(notes) == 3 and "Please take this one" in notes[0] and "was unassigned" in notes[0]
        assert "nobody (unassigned)" in notes[2]

    def test_admin_cannot_assign_homeowner(self, admin, homeowner):
        app = ApplicationFactory()
        res = client_for(admin).post(u("ops-assign", app.id), {"staff_id": str(homeowner.id)}, format="json")
        assert res.status_code == 400
        app.refresh_from_db()
        assert app.assigned_staff is None

    def test_second_claim_conflicts(self, staff, staff2):
        """Service contract: once claimed, a second claim raises. (The row-lock race itself
        is proven with real threads in TestConcurrentClaim below.)"""
        from applications.services import AssignmentConflict, claim_application

        app = ApplicationFactory()
        claim_application(application_id=app.id, by_user=staff)
        with pytest.raises(AssignmentConflict):
            claim_application(application_id=app.id, by_user=staff2)


@pytest.mark.django_db(transaction=True)
class TestConcurrentClaim:
    def test_two_staff_race_for_one_lead(self, staff, staff2):
        import threading

        from django.db import connection

        from applications.services import AssignmentConflict, claim_application

        app = ApplicationFactory()
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(user):
            try:
                barrier.wait(timeout=5)
                claim_application(application_id=app.id, by_user=user)
                outcomes.append("claimed")
            except AssignmentConflict:
                outcomes.append("conflict")
            except Exception as exc:  # noqa: BLE001
                outcomes.append(f"error: {exc!r}")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(u,)) for u in (staff, staff2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert sorted(outcomes) == ["claimed", "conflict"], outcomes
        app.refresh_from_db()
        assert app.assigned_staff in (staff, staff2)
        assert app.status_history.count() == 1


# ---------------------------------------------------------------------------
# Act-on-assigned rule
# ---------------------------------------------------------------------------
class TestActOnAssigned:
    def test_unassigned_staff_cannot_act(self, staff, staff2):
        app = ApplicationFactory(assigned_staff=staff2, status=S.INTAKE)
        c = client_for(staff)
        assert c.get(u("ops-application", app.id)).status_code == 200  # can read
        assert c.get(u("ops-application", app.id)).data["can_act"] is False
        assert c.post(u("ops-transition", app.id), {"to_status": "eligibility_check"}, format="json").status_code == 403
        assert c.post(u("ops-notes", app.id), {"note": "hi"}, format="json").status_code == 403
        assert c.patch(u("ops-application", app.id), {"estimated_cost": "10.00"}, format="json").status_code == 403
        assert c.post(u("ops-permit-create", app.id), {"permit_type": "building"}, format="json").status_code == 403
        assert c.post(u("ops-visit-create", app.id), {"visit_type": "inspection", "scheduled_for": timezone.now()}, format="json").status_code == 403
        item = app.compliance_items.first() or ComplianceItem.objects.create(application=app, item_type="parking")
        assert c.patch(u("ops-compliance-edit", app.id, child_pk=item.id), {"status": "compliant"}, format="json").status_code == 403
        app.refresh_from_db()
        assert app.status == S.INTAKE and app.status_history.count() == 0

    def test_assigned_staff_can_act(self, staff):
        app = ApplicationFactory(assigned_staff=staff, status=S.INTAKE)
        res = client_for(staff).post(u("ops-transition", app.id), {"to_status": "eligibility_check", "note": "ok"}, format="json")
        assert res.status_code == 200 and res.data["status"] == "eligibility_check"
        assert res.data["status_history"][-1]["changed_by"]["email"] == staff.email

    def test_admin_acts_on_anything(self, admin, staff):
        app = ApplicationFactory(assigned_staff=staff, status=S.INTAKE)
        res = client_for(admin).post(u("ops-transition", app.id), {"to_status": "eligibility_check"}, format="json")
        assert res.status_code == 200

    def test_unassigned_application_requires_claim_first(self, staff):
        app = ApplicationFactory(status=S.INTAKE)
        res = client_for(staff).post(u("ops-transition", app.id), {"to_status": "eligibility_check"}, format="json")
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
class TestTransitions:
    def test_invalid_jump_is_409(self, admin):
        app = ApplicationFactory(status=S.INTAKE)
        res = client_for(admin).post(u("ops-transition", app.id), {"to_status": "construction"}, format="json")
        assert res.status_code == 409 and "Cannot move" in res.data["detail"]
        app.refresh_from_db()
        assert app.status == S.INTAKE

    def test_allowed_transitions_reported(self, admin):
        app = ApplicationFactory(status=S.ELIGIBILITY_CHECK)
        res = client_for(admin).get(u("ops-application", app.id))
        assert set(res.data["allowed_transitions"]) == {"development_permit", "permits", "on_hold", "withdrawn"}

    def test_on_hold_and_resume(self, admin):
        app = ApplicationFactory(status=S.PERMITS)
        c = client_for(admin)
        c.post(u("ops-transition", app.id), {"to_status": "on_hold"}, format="json")
        res = c.get(u("ops-application", app.id))
        assert res.data["allowed_transitions"] == ["permits", "withdrawn"]
        assert c.post(u("ops-transition", app.id), {"to_status": "construction"}, format="json").status_code == 409
        assert c.post(u("ops-transition", app.id), {"to_status": "permits"}, format="json").status_code == 200

    def test_registered_requires_permits_and_inspection(self, admin):
        app = ApplicationFactory(status=S.INSPECTIONS)
        c = client_for(admin)
        # nothing recorded
        res = c.post(u("ops-transition", app.id), {"to_status": "registered"}, format="json")
        assert res.status_code == 409 and "No permits" in res.data["detail"] and "No inspection" in res.data["detail"]
        # permit applied but not approved, inspection scheduled but not completed
        PermitFactory(application=app, permit_type="building", status=PermitStatus.APPLIED)
        PermitFactory(application=app, permit_type="development", status=PermitStatus.NOT_REQUIRED)
        v = VisitFactory(application=app, visit_type=VisitType.INSPECTION, status=VisitStatus.SCHEDULED)
        res = c.post(u("ops-transition", app.id), {"to_status": "registered"}, format="json")
        assert res.status_code == 409 and "Building permit is applied" in res.data["detail"]
        blockers = c.get(u("ops-application", app.id)).data["completion_blockers"]
        assert len(blockers) == 3  # building not approved, no completed inspection, one still open
        # satisfy
        Permit.objects.filter(application=app, permit_type="building").update(status=PermitStatus.APPROVED)
        Visit.objects.filter(pk=v.pk).update(status=VisitStatus.COMPLETED)
        res = c.post(u("ops-transition", app.id), {"to_status": "registered"}, format="json")
        assert res.status_code == 200 and res.data["status"] == "registered"
        assert res.data["completion_blockers"] == []
        assert c.post(u("ops-transition", app.id), {"to_status": "complete"}, format="json").status_code == 200

    def test_site_assessment_visits_do_not_count_as_inspection(self, admin):
        app = ApplicationFactory(status=S.INSPECTIONS)
        PermitFactory(application=app, permit_type="building", status=PermitStatus.APPROVED)
        VisitFactory(application=app, visit_type=VisitType.SITE_ASSESSMENT, status=VisitStatus.COMPLETED)
        res = client_for(admin).post(u("ops-transition", app.id), {"to_status": "registered"}, format="json")
        assert res.status_code == 409

    def test_homeowner_sees_status_changes_but_not_internal_notes(self, admin, homeowner):
        app = ApplicationFactory(homeowner=homeowner, status=S.INTAKE)
        c = client_for(admin)
        c.post(u("ops-notes", app.id), {"note": "Called homeowner, no answer."}, format="json")
        c.post(u("ops-transition", app.id), {"to_status": "eligibility_check", "note": "Looks eligible"}, format="json")
        ops_hist = c.get(u("ops-application", app.id)).data["status_history"]
        assert [h["is_note"] for h in ops_hist] == [True, False]
        ho_hist = client_for(homeowner).get(reverse("homeowner-application", kwargs={"pk": app.id})).data["status_history"]
        assert len(ho_hist) == 1 and ho_hist[0]["to_status"] == "eligibility_check"
        assert "Called homeowner" not in str(ho_hist)


# ---------------------------------------------------------------------------
# Edits: application fields, compliance, permits, visits
# ---------------------------------------------------------------------------
class TestEdits:
    def test_patch_application_fields(self, admin):
        app = ApplicationFactory()
        res = client_for(admin).patch(
            u("ops-application", app.id),
            {"estimated_cost": "12500.50", "pursuing_incentive": True, "land_use_district": "R-CG"},
            format="json",
        )
        assert res.status_code == 200
        assert res.data["estimated_cost"] == "12500.50" and res.data["pursuing_incentive"] is True
        assert res.data["property"]["land_use_district"] == "R-CG"
        assert client_for(admin).patch(u("ops-application", app.id), {"estimated_cost": "-1"}, format="json").status_code == 400

    def test_patch_cannot_touch_status_or_owner(self, admin, other_homeowner):
        app = ApplicationFactory(status=S.INTAKE)
        res = client_for(admin).patch(
            u("ops-application", app.id), {"status": "complete", "homeowner": str(other_homeowner.id)}, format="json"
        )
        assert res.status_code == 200
        app.refresh_from_db()
        assert app.status == S.INTAKE and app.homeowner != other_homeowner

    def test_compliance_edit_and_add_other(self, admin):
        app = ApplicationFactory()
        item = ComplianceItem.objects.create(application=app, item_type="egress_window")
        c = client_for(admin)
        res = c.patch(u("ops-compliance-edit", app.id, child_pk=item.id), {"status": "na", "notes": "No bedrooms below grade"}, format="json")
        assert res.status_code == 200 and res.data["status"] == "na"
        res = c.post(u("ops-compliance-create", app.id), {"notes": "Stair riser height", "status": "needs_work"}, format="json")
        assert res.status_code == 201 and res.data["item_type"] == "other"
        res = c.post(u("ops-compliance-create", app.id), {"notes": "Second other"}, format="json")
        assert res.status_code == 201  # multiple 'other' allowed
        assert c.post(u("ops-compliance-create", app.id), {"status": "compliant"}, format="json").status_code == 400  # notes required

    def test_compliance_item_from_other_application_is_404(self, admin):
        a, b = ApplicationFactory(), ApplicationFactory()
        item = ComplianceItem.objects.create(application=a, item_type="parking")
        res = client_for(admin).patch(u("ops-compliance-edit", b.id, child_pk=item.id), {"status": "compliant"}, format="json")
        assert res.status_code == 404

    def test_permits(self, admin):
        app = ApplicationFactory()
        c = client_for(admin)
        res = c.post(u("ops-permit-create", app.id), {"permit_type": "building", "status": "applied", "applied_date": "2026-09-01"}, format="json")
        assert res.status_code == 201
        pid = res.data["id"]
        assert c.post(u("ops-permit-create", app.id), {"permit_type": "building"}, format="json").status_code == 409
        res = c.patch(u("ops-permit-edit", app.id, child_pk=pid), {"status": "approved", "approved_date": "2026-08-01"}, format="json")
        assert res.status_code == 400  # approved before applied
        res = c.patch(u("ops-permit-edit", app.id, child_pk=pid), {"status": "approved", "approved_date": "2026-09-10", "permit_number": "BP2026-1"}, format="json")
        assert res.status_code == 200 and res.data["status"] == "approved" and res.data["permit_number"] == "BP2026-1"
        res = c.patch(u("ops-permit-edit", app.id, child_pk=pid), {"permit_type": "gas"}, format="json")
        assert res.status_code == 200 and res.data["permit_type"] == "building"  # type is immutable

    def test_visits(self, admin, staff, homeowner):
        app = ApplicationFactory()
        c = client_for(admin)
        when = (timezone.now() + dt.timedelta(days=3)).isoformat()
        res = c.post(u("ops-visit-create", app.id), {"visit_type": "site_assessment", "scheduled_for": when}, format="json")
        assert res.status_code == 201
        assert res.data["assigned_staff"]["id"] == str(admin.id)  # defaults to creator
        vid = res.data["id"]
        res = c.patch(u("ops-visit-edit", app.id, child_pk=vid), {"assigned_staff_id": str(staff.id)}, format="json")
        assert res.status_code == 200 and res.data["assigned_staff"]["id"] == str(staff.id)
        res = c.patch(u("ops-visit-edit", app.id, child_pk=vid), {"assigned_staff_id": str(homeowner.id)}, format="json")
        assert res.status_code == 400  # must be ops
        res = c.patch(u("ops-visit-edit", app.id, child_pk=vid), {"status": "completed", "outcome_notes": "All good"}, format="json")
        assert res.status_code == 200 and res.data["status"] == "completed"
        assert c.post(u("ops-visit-create", app.id), {"visit_type": "inspection"}, format="json").status_code == 400  # missing date


# ---------------------------------------------------------------------------
# Bulk document review (transaction boundary 5)
# ---------------------------------------------------------------------------
class TestDocumentReview:
    def test_accept_and_reject_in_one_call(self, admin):
        app = ApplicationFactory()
        d1 = uploaded_doc(app, "site_plan")
        d2 = uploaded_doc(app, "floor_plans")
        res = client_for(admin).post(
            u("ops-document-review", app.id),
            {"decisions": [
                {"document_id": str(d1.id), "status": "accepted"},
                {"document_id": str(d2.id), "status": "rejected", "notes": "Dimensions missing"},
            ]},
            format="json",
        )
        assert res.status_code == 200, res.data
        d1.refresh_from_db(); d2.refresh_from_db()
        assert d1.status == "accepted" and d2.status == "rejected" and d2.notes == "Dimensions missing"
        note = app.status_history.get()
        assert "Documents reviewed" in note.note and note.from_status == note.to_status

    def test_batch_is_atomic(self, admin):
        app = ApplicationFactory()
        good = uploaded_doc(app, "site_plan")
        not_uploaded = DocumentFactory(application=app, doc_type="land_title")  # no file
        res = client_for(admin).post(
            u("ops-document-review", app.id),
            {"decisions": [
                {"document_id": str(good.id), "status": "accepted"},
                {"document_id": str(not_uploaded.id), "status": "accepted"},
            ]},
            format="json",
        )
        assert res.status_code == 400 and "nothing has been uploaded" in str(res.data)
        good.refresh_from_db()
        assert good.status == "uploaded"  # first decision rolled back
        assert app.status_history.count() == 0

    def test_reject_requires_note(self, admin):
        app = ApplicationFactory()
        d = uploaded_doc(app)
        res = client_for(admin).post(u("ops-document-review", app.id), {"decisions": [{"document_id": str(d.id), "status": "rejected"}]}, format="json")
        assert res.status_code == 400
        d.refresh_from_db()
        assert d.status == "uploaded"

    def test_unknown_or_foreign_document_fails_whole_batch(self, admin):
        app, other = ApplicationFactory(), ApplicationFactory()
        mine = uploaded_doc(app)
        foreign = uploaded_doc(other)
        res = client_for(admin).post(
            u("ops-document-review", app.id),
            {"decisions": [{"document_id": str(mine.id), "status": "accepted"}, {"document_id": str(foreign.id), "status": "accepted"}]},
            format="json",
        )
        assert res.status_code == 400
        mine.refresh_from_db(); foreign.refresh_from_db()
        assert mine.status == "uploaded" and foreign.status == "uploaded"

    def test_empty_batch_rejected(self, admin):
        app = ApplicationFactory()
        assert client_for(admin).post(u("ops-document-review", app.id), {"decisions": []}, format="json").status_code == 400

    def test_accepted_document_locked_for_homeowner_then_rejected_reopens(self, admin, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        d = uploaded_doc(app)
        client_for(admin).post(u("ops-document-review", app.id), {"decisions": [{"document_id": str(d.id), "status": "accepted"}]}, format="json")
        up = reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": d.id})
        assert client_for(homeowner).post(up, {"file": SimpleUploadedFile("n.pdf", PDF)}, format="multipart").status_code == 409
        client_for(admin).post(u("ops-document-review", app.id), {"decisions": [{"document_id": str(d.id), "status": "rejected", "notes": "blurry"}]}, format="json")
        assert client_for(homeowner).post(up, {"file": SimpleUploadedFile("n.pdf", PDF)}, format="multipart").status_code == 200

    def test_ops_download(self, staff, staff2):
        app = ApplicationFactory(assigned_staff=staff2)
        d = uploaded_doc(app)
        res = client_for(staff).get(u("ops-document-download", app.id, doc_pk=d.id))  # any ops user may read
        assert res.status_code == 200 and b"".join(res.streaming_content) == PDF


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
class TestNotes:
    def test_add_note(self, admin):
        app = ApplicationFactory(status=S.PERMITS)
        res = client_for(admin).post(u("ops-notes", app.id), {"note": "Spoke to the City; DP not needed."}, format="json")
        assert res.status_code == 200
        row = ApplicationStatusHistory.objects.get(application=app)
        assert row.from_status == row.to_status == S.PERMITS and row.changed_by == admin
        assert res.data["status_history"][-1]["is_note"] is True

    def test_blank_note_rejected(self, admin):
        app = ApplicationFactory()
        assert client_for(admin).post(u("ops-notes", app.id), {"note": "   "}, format="json").status_code == 400
        assert app.status_history.count() == 0
