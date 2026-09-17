"""
Milestone 5: Celery notification tasks. Tasks run eagerly (conftest), and Django's test
setup routes email to django.core.mail.outbox. Because the services enqueue on commit,
the capture fixture executes on_commit callbacks inside the test transaction.
"""

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from applications import tasks
from applications.enums import ApplicationStatus as S
from tests.api_helpers import client_for, intake_payload
from tests.factories import ApplicationFactory, DocumentFactory, UserFactory

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.4\n%x\n"


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    def _ctx():
        return django_capture_on_commit_callbacks(execute=True)

    return _ctx


class TestNewLead:
    def test_staff_and_admin_notified_not_homeowners(self, homeowner, other_homeowner, staff, admin, commit):
        inactive = UserFactory(role="staff", is_active=False)
        with commit():
            res = client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
        assert res.status_code == 201
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert set(msg.to) == {staff.email, admin.email}
        assert inactive.email not in msg.to and other_homeowner.email not in msg.to
        assert "New lead" in msg.subject and "1234 17 Ave SW" in msg.body
        assert f"/ops/applications/{res.data['id']}" in msg.body

    def test_not_sent_if_intake_rolls_back(self, homeowner, staff, commit):
        from unittest import mock

        from applications.models import Document

        with commit(), mock.patch.object(Document.objects, "bulk_create", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
        assert mail.outbox == []

    def test_task_tolerates_missing_application(self):
        import uuid

        assert tasks.notify_staff_new_lead(str(uuid.uuid4())) == 0
        assert mail.outbox == []

    def test_no_ops_users_means_no_email(self, homeowner, commit):
        with commit():
            client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
        assert mail.outbox == []


class TestStatusChange:
    def test_homeowner_emailed_on_ops_transition(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner, status=S.INTAKE)
        with commit():
            client_for(admin).post(
                reverse("ops-transition", kwargs={"pk": app.id}),
                {"to_status": "eligibility_check", "note": "Looks good so far"},
                format="json",
            )
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == [homeowner.email]
        assert "Eligibility check" in msg.subject
        assert "Looks good so far" in msg.body and f"/app/applications/{app.id}" in msg.body

    def test_internal_note_sends_nothing(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner)
        with commit():
            client_for(admin).post(reverse("ops-notes", kwargs={"pk": app.id}), {"note": "internal"}, format="json")
        assert mail.outbox == []

    def test_failed_transition_sends_nothing(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner, status=S.INTAKE)
        with commit():
            res = client_for(admin).post(reverse("ops-transition", kwargs={"pk": app.id}), {"to_status": "complete"}, format="json")
        assert res.status_code == 409 and mail.outbox == []

    def test_homeowner_withdraw_notifies_assigned_staff(self, homeowner, staff, admin, commit):
        app = ApplicationFactory(homeowner=homeowner, assigned_staff=staff)
        with commit():
            client_for(homeowner).post(reverse("homeowner-application-withdraw", kwargs={"pk": app.id}), {}, format="json")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [staff.email]  # assigned person, not everyone
        assert "Withdrawn" in mail.outbox[0].subject

    def test_homeowner_withdraw_unassigned_notifies_all_ops(self, homeowner, staff, admin, commit):
        app = ApplicationFactory(homeowner=homeowner)
        with commit():
            client_for(homeowner).post(reverse("homeowner-application-withdraw", kwargs={"pk": app.id}), {}, format="json")
        assert set(mail.outbox[0].to) == {staff.email, admin.email}

    def test_inactive_homeowner_not_emailed(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner, status=S.INTAKE)
        homeowner.is_active = False
        homeowner.save()
        with commit():
            client_for(admin).post(reverse("ops-transition", kwargs={"pk": app.id}), {"to_status": "eligibility_check"}, format="json")
        assert mail.outbox == []


class TestDocuments:
    def test_upload_notifies_assigned_staff(self, homeowner, staff, commit):
        app = ApplicationFactory(homeowner=homeowner, assigned_staff=staff)
        doc = DocumentFactory(application=app, doc_type="site_plan")
        with commit():
            client_for(homeowner).post(
                reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}),
                {"file": SimpleUploadedFile("f.pdf", PDF)},
                format="multipart",
            )
        assert len(mail.outbox) == 1 and mail.outbox[0].to == [staff.email]
        assert "Uploaded Site plan" in mail.outbox[0].subject

    def test_review_emails_homeowner_with_reasons(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner)
        d1 = DocumentFactory(application=app, doc_type="site_plan")
        d2 = DocumentFactory(application=app, doc_type="floor_plans")
        for d in (d1, d2):
            d.file.save("f.pdf", SimpleUploadedFile("f.pdf", PDF), save=False)
            d.status = "uploaded"
            d.save()
        with commit():
            res = client_for(admin).post(
                reverse("ops-document-review", kwargs={"pk": app.id}),
                {"decisions": [
                    {"document_id": str(d1.id), "status": "accepted"},
                    {"document_id": str(d2.id), "status": "rejected", "notes": "Add room dimensions"},
                ]},
                format="json",
            )
        assert res.status_code == 200
        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert mail.outbox[0].to == [homeowner.email]
        assert "Accepted:" in body and "Site plan" in body
        assert "Needs another upload:" in body and "Floor plans: Add room dimensions" in body

    def test_failed_review_sends_nothing(self, homeowner, admin, commit):
        app = ApplicationFactory(homeowner=homeowner)
        d = DocumentFactory(application=app)  # no file
        with commit():
            res = client_for(admin).post(
                reverse("ops-document-review", kwargs={"pk": app.id}),
                {"decisions": [{"document_id": str(d.id), "status": "accepted"}]},
                format="json",
            )
        assert res.status_code == 400 and mail.outbox == []


class TestBrokerOutage:
    def test_write_succeeds_when_enqueue_fails(self, homeowner, admin, commit, caplog):
        from unittest import mock

        app = ApplicationFactory(homeowner=homeowner, status=S.INTAKE)
        # The patch must outlive the commit() context, because on_commit callbacks run when
        # commit() exits.
        with mock.patch.object(tasks.email_homeowner_status_change, "delay", side_effect=ConnectionError("broker down")):
            with commit():
                res = client_for(admin).post(reverse("ops-transition", kwargs={"pk": app.id}), {"to_status": "eligibility_check"}, format="json")
        assert res.status_code == 200
        app.refresh_from_db()
        assert app.status == S.ELIGIBILITY_CHECK
        assert "Could not enqueue notification task" in caplog.text
