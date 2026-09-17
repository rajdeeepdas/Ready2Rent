"""Milestone 3: document upload / download with local storage and ownership checks."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from applications.enums import DocumentStatus
from applications.models import Document
from tests.api_helpers import client_for, intake_payload
from tests.factories import ApplicationFactory, DocumentFactory

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def upload_url(app_id, doc_id):
    return reverse("homeowner-document-upload", kwargs={"pk": app_id, "doc_pk": doc_id})


def download_url(app_id, doc_id):
    return reverse("homeowner-document-download", kwargs={"pk": app_id, "doc_pk": doc_id})


@pytest.fixture
def submitted(homeowner):
    """An application created through the real intake endpoint, plus its site_plan doc."""
    res = client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
    assert res.status_code == 201
    doc = Document.objects.get(application_id=res.data["id"], doc_type="site_plan")
    return res.data["id"], doc


class TestUpload:
    def test_upload_pdf_sets_status_and_stores_file(self, homeowner, submitted, settings):
        app_id, doc = submitted
        f = SimpleUploadedFile("Site Plan (final).pdf", PDF, content_type="application/pdf")
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {"file": f}, format="multipart")
        assert res.status_code == 200, res.data
        assert res.data["status"] == "uploaded"
        assert res.data["file_name"].endswith(".pdf")
        assert res.data["download_url"] == download_url(app_id, doc.id)

        doc.refresh_from_db()
        assert doc.status == DocumentStatus.UPLOADED
        assert doc.uploaded_by == homeowner and doc.uploaded_at is not None
        assert doc.file.name.startswith(f"applications/{app_id}/site_plan/")
        assert (settings.MEDIA_ROOT / doc.file.name).read_bytes() == PDF

    @pytest.mark.parametrize("name,content", [("photo.png", PNG), ("photo.jpg", JPG), ("photo.jpeg", JPG)])
    def test_images_allowed(self, homeowner, submitted, name, content):
        app_id, doc = submitted
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile(name, content)}, format="multipart")
        assert res.status_code == 200

    @pytest.mark.parametrize(
        "name,content",
        [
            ("evil.exe", b"MZ\x90\x00" + b"\x00" * 20),
            ("script.html", b"<html>"),
            ("noext", PDF),
            ("renamed.pdf", b"MZ\x90\x00" + b"\x00" * 20),  # wrong magic bytes
            ("fake.png", PDF),
        ],
    )
    def test_rejects_disallowed_types(self, homeowner, submitted, name, content):
        app_id, doc = submitted
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile(name, content)}, format="multipart")
        assert res.status_code == 400 and "file" in res.data
        doc.refresh_from_db()
        assert doc.status == "required" and not doc.file

    def test_rejects_empty_and_oversized(self, homeowner, submitted, settings):
        app_id, doc = submitted
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("e.pdf", b"")}, format="multipart")
        assert res.status_code == 400
        settings.MAX_UPLOAD_MB = 1
        big = SimpleUploadedFile("big.pdf", PDF + b"\x00" * (1024 * 1024 + 1))
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {"file": big}, format="multipart")
        assert res.status_code == 400 and "larger than" in str(res.data["file"])

    def test_reupload_replaces_file_and_removes_old_one(self, homeowner, submitted, settings):
        app_id, doc = submitted
        c = client_for(homeowner)
        c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v1.pdf", PDF)}, format="multipart")
        doc.refresh_from_db()
        old_path = settings.MEDIA_ROOT / doc.file.name
        assert old_path.exists()
        res = c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v2.pdf", PDF)}, format="multipart")
        assert res.status_code == 200
        doc.refresh_from_db()
        assert doc.file.name.endswith("v2.pdf") and not old_path.exists()

    def test_rejected_document_can_be_reuploaded(self, homeowner, submitted):
        app_id, doc = submitted
        c = client_for(homeowner)
        c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v1.pdf", PDF)}, format="multipart")
        Document.objects.filter(pk=doc.pk).update(status=DocumentStatus.REJECTED)
        res = c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v2.pdf", PDF)}, format="multipart")
        assert res.status_code == 200 and res.data["status"] == "uploaded"

    def test_accepted_document_is_locked(self, homeowner, submitted):
        app_id, doc = submitted
        c = client_for(homeowner)
        c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v1.pdf", PDF)}, format="multipart")
        Document.objects.filter(pk=doc.pk).update(status=DocumentStatus.ACCEPTED)
        res = c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("v2.pdf", PDF)}, format="multipart")
        assert res.status_code == 409
        doc.refresh_from_db()
        assert doc.status == "accepted" and doc.file.name.endswith("v1.pdf")

    def test_missing_file_field(self, homeowner, submitted):
        app_id, doc = submitted
        res = client_for(homeowner).post(upload_url(app_id, doc.id), {}, format="multipart")
        assert res.status_code == 400

    def test_cannot_upload_to_other_homeowners_document(self, homeowner, other_homeowner):
        theirs = ApplicationFactory(homeowner=other_homeowner)
        doc = DocumentFactory(application=theirs)
        res = client_for(homeowner).post(upload_url(theirs.id, doc.id), {"file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart")
        assert res.status_code == 404
        doc.refresh_from_db()
        assert not doc.file

    def test_document_must_belong_to_application_in_url(self, homeowner):
        """Mixing a doc id from application A with application B's URL is a 404."""
        a = ApplicationFactory(homeowner=homeowner)
        b = ApplicationFactory(homeowner=homeowner)
        doc_a = DocumentFactory(application=a)
        res = client_for(homeowner).post(upload_url(b.id, doc_a.id), {"file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart")
        assert res.status_code == 404

    def test_staff_cannot_use_homeowner_upload(self, staff, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        res = client_for(staff).post(upload_url(app.id, doc.id), {"file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart")
        assert res.status_code == 403


class TestOtherDocuments:
    def test_add_other_document_with_file(self, homeowner, submitted):
        app_id, _ = submitted
        url = reverse("homeowner-document-create", kwargs={"pk": app_id})
        res = client_for(homeowner).post(
            url, {"file": SimpleUploadedFile("receipt.jpg", JPG), "notes": "Contractor quote"}, format="multipart"
        )
        assert res.status_code == 201
        assert res.data["doc_type"] == "other" and res.data["status"] == "uploaded"
        assert res.data["notes"] == "Contractor quote"
        assert Document.objects.filter(application_id=app_id, doc_type="other").count() == 1

    def test_other_document_requires_file(self, homeowner, submitted):
        app_id, _ = submitted
        url = reverse("homeowner-document-create", kwargs={"pk": app_id})
        assert client_for(homeowner).post(url, {"notes": "no file"}, format="multipart").status_code == 400


class TestDownload:
    def test_owner_can_download(self, homeowner, submitted):
        app_id, doc = submitted
        c = client_for(homeowner)
        c.post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("plan.pdf", PDF)}, format="multipart")
        res = c.get(download_url(app_id, doc.id))
        assert res.status_code == 200
        assert b"".join(res.streaming_content) == PDF
        assert "attachment" in res["Content-Disposition"] and "plan.pdf" in res["Content-Disposition"]

    def test_download_before_upload_is_404(self, homeowner, submitted):
        app_id, doc = submitted
        assert client_for(homeowner).get(download_url(app_id, doc.id)).status_code == 404

    def test_other_homeowner_cannot_download(self, homeowner, other_homeowner, submitted):
        app_id, doc = submitted
        client_for(homeowner).post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("plan.pdf", PDF)}, format="multipart")
        assert client_for(other_homeowner).get(download_url(app_id, doc.id)).status_code == 404

    def test_media_is_not_served_publicly(self, homeowner, submitted, client):
        """The raw MEDIA_URL path must not be routable, even in DEBUG."""
        app_id, doc = submitted
        client_for(homeowner).post(upload_url(app_id, doc.id), {"file": SimpleUploadedFile("plan.pdf", PDF)}, format="multipart")
        doc.refresh_from_db()
        res = client.get(f"/media/{doc.file.name}")
        assert res.status_code == 404
