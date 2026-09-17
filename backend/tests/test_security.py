"""
Security regression tests for the pre-launch review (DECISIONS.md M7-1).
Each class maps to one finding that was fixed.
"""

from unittest import mock

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from applications import tasks
from applications.models import Document
from config.security import validate_secret_key
from core.throttles import ScopedWriteThrottle
from tests.api_helpers import client_for, intake_payload
from tests.factories import ApplicationFactory, DocumentFactory, UserFactory

pytestmark = pytest.mark.django_db
PASSWORD = "Str0ng-and-l0ng-passw0rd!"
PDF = b"%PDF-1.4\n%x\n"


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def csrf_client():
    c = APIClient(enforce_csrf_checks=True)
    c.get(reverse("auth-csrf"))
    return c, {"HTTP_X_CSRFTOKEN": c.cookies["csrftoken"].value}


# ---------------------------------------------------------------------------
# 1. Login CSRF
# ---------------------------------------------------------------------------
class TestLoginCsrf:
    @pytest.mark.parametrize("name", ["auth-login", "auth-register"])
    def test_html_form_post_is_refused(self, name):
        """A cross-site <form> can only send form-encoded or multipart bodies."""
        UserFactory(email="victim@example.com", password=PASSWORD)
        res = APIClient().post(reverse(name), {"email": "victim@example.com", "password": PASSWORD})  # multipart
        assert res.status_code in (403, 415)
        assert "r2r_refresh" not in res.cookies
        res = APIClient().post(
            reverse(name), "email=victim%40example.com&password=x", content_type="application/x-www-form-urlencoded"
        )
        assert res.status_code in (403, 415)

    @pytest.mark.parametrize("name", ["auth-login", "auth-register"])
    def test_json_without_csrf_token_is_refused(self, name):
        UserFactory(email="victim@example.com", password=PASSWORD)
        c = APIClient(enforce_csrf_checks=True)
        res = c.post(reverse(name), {"email": "victim@example.com", "password": PASSWORD}, format="json")
        assert res.status_code == 403 and "CSRF" in res.data["detail"]
        assert "r2r_refresh" not in res.cookies

    def test_foreign_origin_refused_even_with_token(self, settings):
        UserFactory(email="victim@example.com", password=PASSWORD)
        c, headers = csrf_client()
        res = c.post(
            reverse("auth-login"),
            {"email": "victim@example.com", "password": PASSWORD},
            format="json",
            HTTP_ORIGIN="https://evil.example",
            **headers,
        )
        assert res.status_code == 403

    def test_same_origin_json_with_token_works(self):
        UserFactory(email="user@example.com", password=PASSWORD)
        c, headers = csrf_client()
        res = c.post(reverse("auth-login"), {"email": "user@example.com", "password": PASSWORD}, format="json", **headers)
        assert res.status_code == 200 and "r2r_refresh" in res.cookies


# ---------------------------------------------------------------------------
# 2. Request body size
# ---------------------------------------------------------------------------
class TestBodySize:
    def test_oversized_json_body_rejected(self, homeowner):
        big = intake_payload(other_issues="x" * (3 * 1024 * 1024))  # 3 MB, above Django's 2.5 MB cap
        res = client_for(homeowner).post(reverse("homeowner-applications"), big, format="json")
        assert res.status_code in (400, 413)
        from applications.models import Application

        assert Application.objects.count() == 0

    def test_file_uploads_are_not_limited_by_the_json_cap(self, homeowner, settings):
        settings.MAX_UPLOAD_MB = 5
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        three_mb = SimpleUploadedFile("big.pdf", PDF + b"\x00" * (3 * 1024 * 1024))
        res = client_for(homeowner).post(
            reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}), {"file": three_mb}, format="multipart"
        )
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# 3. Invalid queue filter no longer 500s
# ---------------------------------------------------------------------------
class TestQueueFilterValidation:
    @pytest.mark.parametrize("value", ["not-a-uuid", "1 OR 1=1", "'; DROP TABLE x;--"])
    def test_bad_assigned_value_is_400(self, staff, value):
        res = client_for(staff).get(reverse("ops-queue"), {"assigned": value})
        assert res.status_code == 400 and "assigned" in res.data

    def test_injection_in_search_is_inert(self, staff):
        ApplicationFactory()
        res = client_for(staff).get(reverse("ops-queue"), {"q": "' OR '1'='1", "ordering": "id; DROP TABLE x"})
        assert res.status_code == 200 and res.data["count"] == 0


# ---------------------------------------------------------------------------
# 4. Email header injection
# ---------------------------------------------------------------------------
class TestEmailSubjects:
    def test_newlines_in_address_cannot_break_headers(self, staff):
        app = ApplicationFactory()
        app.property.street_address = "12 Main St\r\nBcc: attacker@example.com\r\nSubject: hi"
        app.property.save()
        assert tasks.notify_staff_new_lead(str(app.id)) == 1
        msg = mail.outbox[0]
        assert "\n" not in msg.subject and "\r" not in msg.subject
        assert msg.bcc == [] and "attacker@example.com" not in msg.to

    def test_long_subject_is_truncated(self):
        assert len(tasks._subject("x" * 500)) == 150


# ---------------------------------------------------------------------------
# 5. Abuse limits on writes
# ---------------------------------------------------------------------------
class TestWriteThrottles:
    def test_intake_submissions_throttled_per_user(self, homeowner, other_homeowner):
        with mock.patch.object(ScopedWriteThrottle, "THROTTLE_RATES", {"intake": "2/day", "uploads": "100/hour"}):
            c = client_for(homeowner)
            url = reverse("homeowner-applications")
            assert c.post(url, intake_payload(), format="json").status_code == 201
            assert c.post(url, intake_payload(), format="json").status_code == 201
            assert c.post(url, intake_payload(), format="json").status_code == 429
            assert c.get(url).status_code == 200  # reads are never throttled
            # A different user has their own bucket
            assert client_for(other_homeowner).post(url, intake_payload(), format="json").status_code == 201

    def test_uploads_throttled_per_user(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        url = reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id})
        with mock.patch.object(ScopedWriteThrottle, "THROTTLE_RATES", {"intake": "10/day", "uploads": "2/hour"}):
            c = client_for(homeowner)
            for _ in range(2):
                assert c.post(url, {"file": SimpleUploadedFile("f.pdf", PDF)}, format="multipart").status_code == 200
            assert c.post(url, {"file": SimpleUploadedFile("f.pdf", PDF)}, format="multipart").status_code == 429

    def test_extra_documents_capped_per_application(self, homeowner, settings):
        settings.MAX_OTHER_DOCUMENTS = 2
        app = ApplicationFactory(homeowner=homeowner)
        url = reverse("homeowner-document-create", kwargs={"pk": app.id})
        c = client_for(homeowner)
        for _ in range(2):
            assert c.post(url, {"file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart").status_code == 201
        res = c.post(url, {"file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart")
        assert res.status_code == 400 and "limit 2" in str(res.data)
        assert Document.objects.filter(application=app, doc_type="other").count() == 2

    def test_upload_endpoint_refuses_json_body(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        res = client_for(homeowner).post(
            reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}), {"file": "x"}, format="json"
        )
        assert res.status_code == 415


# ---------------------------------------------------------------------------
# 6. Production configuration guards
# ---------------------------------------------------------------------------
class TestSecretKeyGuard:
    @pytest.mark.parametrize(
        "key",
        ["", "short", "change-me-generate-a-long-random-string", "a" * 80, "django-insecure-" + "k" * 60],
    )
    def test_weak_keys_refused(self, key):
        with pytest.raises(ImproperlyConfigured):
            validate_secret_key(key)

    def test_strong_key_accepted(self):
        import secrets

        validate_secret_key(secrets.token_urlsafe(64))


class TestResponseHardening:
    def test_download_is_attachment_with_nosniff(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        doc.file.save("x.pdf", SimpleUploadedFile("x.pdf", PDF), save=False)
        doc.status = "uploaded"
        doc.save()
        res = client_for(homeowner).get(reverse("homeowner-document-download", kwargs={"pk": app.id, "doc_pk": doc.id}))
        assert res["Content-Disposition"].startswith("attachment")
        assert res["X-Content-Type-Options"] == "nosniff"

    def test_api_responses_deny_framing(self, homeowner):
        res = client_for(homeowner).get(reverse("homeowner-applications"))
        assert res["X-Frame-Options"] == "DENY"
        assert res["Referrer-Policy"] == "same-origin"

    def test_stored_script_is_returned_as_inert_json(self, homeowner, staff):
        """No HTML is ever rendered by the API; React escapes on display."""
        payload = intake_payload(property={"street_address": "<script>alert(1)</script>"})
        res = client_for(homeowner).post(reverse("homeowner-applications"), payload, format="json")
        assert res.status_code == 201
        assert res["Content-Type"].startswith("application/json")
        q = client_for(staff).get(reverse("ops-queue"))
        assert q["Content-Type"].startswith("application/json")
