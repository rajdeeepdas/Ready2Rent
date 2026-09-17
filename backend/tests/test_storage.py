"""
Free-tier deployment: storage selection, Supabase S3 options, storage-agnostic document access
control, and the release command that replaces Render's paid pre-deploy step.
"""

import datetime as dt

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from applications.models import Document
from config.storage import build_storages
from tests.api_helpers import client_for
from tests.factories import ApplicationFactory, DocumentFactory

PDF = b"%PDF-1.4\n%storage test\n"
S3 = {
    "endpoint_url": "https://abcdefghijklmnop.storage.supabase.co/storage/v1/s3",
    "region_name": "us-west-2",
    "access_key": "test-access-key",
    "secret_key": "test-secret-key",
    "bucket_name": "documents",
}


class TestBuildStorages:
    def test_local_filesystem_without_supabase(self):
        s = build_storages(debug=True, s3=None)
        assert s["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
        assert s["staticfiles"]["BACKEND"].endswith("StaticFilesStorage")

    def test_production_static_files_are_hashed(self):
        s = build_storages(debug=False, s3=None)
        assert s["staticfiles"]["BACKEND"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"

    def test_supabase_s3_options(self):
        opts = build_storages(debug=False, s3=S3)["default"]
        assert opts["BACKEND"] == "storages.backends.s3.S3Storage"
        o = opts["OPTIONS"]
        assert o["endpoint_url"] == S3["endpoint_url"] and o["region_name"] == "us-west-2"
        assert o["file_overwrite"] is False  # same-named uploads must not replace each other
        assert o["default_acl"] is None  # bucket stays private
        cfg = o["client_config"]
        assert cfg.signature_version == "s3v4"
        assert cfg.s3 == {"addressing_style": "path"}  # required by Supabase
        assert cfg.request_checksum_calculation == "when_required"
        assert cfg.response_checksum_validation == "when_required"

    @pytest.mark.parametrize("missing", ["region_name", "access_key", "secret_key", "bucket_name"])
    def test_partial_configuration_fails_loudly(self, missing):
        with pytest.raises(ImproperlyConfigured, match=missing):
            build_storages(debug=False, s3={**S3, missing: ""})

    def test_s3_backend_instantiates_offline(self):
        """Constructing the backend must not need the network (it is created at import time)."""
        from storages.backends.s3 import S3Storage

        storage = S3Storage(**build_storages(debug=False, s3=S3)["default"]["OPTIONS"])
        assert storage.bucket_name == "documents"
        assert storage.file_overwrite is False


@pytest.mark.django_db
class TestAccessControlOnObjectStorage:
    """Run the document flow on a storage with no local paths, as Supabase Storage has none.
    Proves the views only use the storage API and still enforce ownership."""

    @pytest.fixture(autouse=True)
    def in_memory_storage(self, settings):
        settings.STORAGES = {
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        }

    def _upload(self, user, app, doc, name="plan.pdf", content=PDF):
        return client_for(user).post(
            reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}),
            {"file": SimpleUploadedFile(name, content)},
            format="multipart",
        )

    def test_upload_download_and_ownership(self, homeowner, other_homeowner, staff):
        from django.core.files.storage import default_storage

        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app, doc_type="site_plan")
        assert self._upload(homeowner, app, doc).status_code == 200
        doc.refresh_from_db()
        assert default_storage.exists(doc.file.name)
        assert default_storage.__class__.__name__ == "InMemoryStorage"

        url = reverse("homeowner-document-download", kwargs={"pk": app.id, "doc_pk": doc.id})
        res = client_for(homeowner).get(url)
        assert res.status_code == 200 and b"".join(res.streaming_content) == PDF
        assert res["Content-Disposition"].startswith("attachment")

        assert client_for(other_homeowner).get(url).status_code == 404
        ops_url = reverse("ops-document-download", kwargs={"pk": app.id, "doc_pk": doc.id})
        assert client_for(staff).get(ops_url).status_code == 200
        assert client_for(homeowner).get(ops_url).status_code == 403

    def test_replace_deletes_previous_object(self, homeowner):
        from django.core.files.storage import default_storage

        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app, doc_type="site_plan")
        self._upload(homeowner, app, doc, "v1.pdf")
        doc.refresh_from_db()
        first = doc.file.name
        self._upload(homeowner, app, doc, "v2.pdf")
        doc.refresh_from_db()
        assert doc.file.name != first
        assert not default_storage.exists(first) and default_storage.exists(doc.file.name)

    def test_same_filename_other_documents_do_not_overwrite(self, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        url = reverse("homeowner-document-create", kwargs={"pk": app.id})
        c = client_for(homeowner)
        a = c.post(url, {"file": SimpleUploadedFile("scan.pdf", PDF + b"A")}, format="multipart")
        b = c.post(url, {"file": SimpleUploadedFile("scan.pdf", PDF + b"B")}, format="multipart")
        assert a.status_code == b.status_code == 201
        names = list(Document.objects.filter(application=app, doc_type="other").values_list("file", flat=True))
        assert len(set(names)) == 2


@pytest.mark.django_db
class TestReleaseCommand:
    def test_migrates_and_flushes_expired_tokens(self, homeowner, capsys):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        now = timezone.now()
        OutstandingToken.objects.create(user=homeowner, jti="expired", token="x", created_at=now - dt.timedelta(days=9), expires_at=now - dt.timedelta(days=2))
        OutstandingToken.objects.create(user=homeowner, jti="current", token="y", created_at=now, expires_at=now + dt.timedelta(days=7))

        call_command("release", verbosity=0)

        out = capsys.readouterr().out
        assert "applying migrations" in out and "release: done" in out
        assert list(OutstandingToken.objects.values_list("jti", flat=True)) == ["current"]

    def test_is_safe_to_run_repeatedly(self):
        call_command("release", verbosity=0)
        call_command("release", verbosity=0)
