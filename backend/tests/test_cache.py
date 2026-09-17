"""Milestone 5: the ops queue is served from Redis and invalidated on every write."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from applications.cache import queue_version
from tests.api_helpers import client_for, intake_payload
from tests.factories import ApplicationFactory, DocumentFactory, PermitFactory, UserFactory

pytestmark = pytest.mark.django_db

QUEUE = reverse("ops-queue")
SUMMARY = reverse("ops-queue-summary")
PDF = b"%PDF-1.4\n%x\n"


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


def get(client, url, params=None):
    res = client.get(url, params or {})
    assert res.status_code == 200
    return res


class TestHitMiss:
    def test_second_read_is_a_hit_with_same_body(self, staff):
        ApplicationFactory()
        c = client_for(staff)
        first = get(c, QUEUE)
        second = get(c, QUEUE)
        assert first["X-Cache"] == "MISS" and second["X-Cache"] == "HIT"
        assert first.data == second.data

    def test_different_filters_are_different_entries(self, staff):
        ApplicationFactory()
        c = client_for(staff)
        get(c, QUEUE)
        assert get(c, QUEUE, {"status": "all"})["X-Cache"] == "MISS"
        assert get(c, QUEUE, {"status": "all"})["X-Cache"] == "HIT"
        assert get(c, QUEUE, {"page": "1"})["X-Cache"] == "MISS"  # different param set

    def test_shared_across_staff_when_not_personal(self, staff):
        ApplicationFactory()
        other = UserFactory(role="staff")
        get(client_for(staff), QUEUE)
        assert get(client_for(other), QUEUE)["X-Cache"] == "HIT"

    def test_assigned_me_is_per_user(self, staff):
        other = UserFactory(role="staff")
        mine = ApplicationFactory(assigned_staff=staff)
        ApplicationFactory(assigned_staff=other)
        a = get(client_for(staff), QUEUE, {"assigned": "me"})
        b = get(client_for(other), QUEUE, {"assigned": "me"})
        assert a["X-Cache"] == "MISS" and b["X-Cache"] == "MISS"  # not shared
        assert [r["id"] for r in a.data["results"]] == [str(mine.id)]
        assert [r["id"] for r in b.data["results"]] != [str(mine.id)]

    def test_summary_is_per_user_and_cached(self, staff):
        other = UserFactory(role="staff")
        ApplicationFactory(assigned_staff=staff)
        c = client_for(staff)
        assert get(c, SUMMARY)["X-Cache"] == "MISS"
        assert get(c, SUMMARY)["X-Cache"] == "HIT"
        res = get(client_for(other), SUMMARY)
        assert res["X-Cache"] == "MISS" and res.data["mine"] == 0

    def test_ttl_uses_setting(self, staff, settings):
        from unittest import mock

        settings.OPS_QUEUE_CACHE_SECONDS = 7
        with mock.patch("applications.cache.cache.set") as m:
            get(client_for(staff), QUEUE)
        assert m.call_args.kwargs["timeout"] == 7


class TestInvalidation:
    def _warm(self, staff):
        c = client_for(staff)
        get(c, QUEUE)
        get(c, SUMMARY)
        assert get(c, QUEUE)["X-Cache"] == "HIT"
        return c

    def test_new_intake_invalidates(self, staff, homeowner):
        c = self._warm(staff)
        v = queue_version()
        client_for(homeowner).post(reverse("homeowner-applications"), intake_payload(), format="json")
        assert queue_version() > v
        res = get(c, QUEUE)
        assert res["X-Cache"] == "MISS" and res.data["count"] == 1
        assert get(c, SUMMARY)["X-Cache"] == "MISS"

    def test_transition_invalidates(self, admin, staff):
        app = ApplicationFactory(status="intake")
        c = self._warm(staff)
        client_for(admin).post(reverse("ops-transition", kwargs={"pk": app.id}), {"to_status": "eligibility_check"}, format="json")
        res = get(c, QUEUE)
        assert res["X-Cache"] == "MISS" and res.data["results"][0]["status"] == "eligibility_check"

    def test_claim_invalidates(self, staff):
        app = ApplicationFactory()
        c = self._warm(staff)
        c.post(reverse("ops-claim", kwargs={"pk": app.id}), {}, format="json")
        res = get(c, QUEUE)
        assert res["X-Cache"] == "MISS" and res.data["results"][0]["assigned_staff"]["id"] == str(staff.id)

    def test_homeowner_upload_invalidates_pending_count(self, staff, homeowner):
        app = ApplicationFactory(homeowner=homeowner)
        doc = DocumentFactory(application=app)
        c = self._warm(staff)
        assert get(c, QUEUE).data["results"][0]["docs_pending_review"] == 0
        client_for(homeowner).post(
            reverse("homeowner-document-upload", kwargs={"pk": app.id, "doc_pk": doc.id}),
            {"file": SimpleUploadedFile("f.pdf", PDF)},
            format="multipart",
        )
        res = get(c, QUEUE)
        assert res["X-Cache"] == "MISS" and res.data["results"][0]["docs_pending_review"] == 1

    def test_child_edit_invalidates(self, admin, staff):
        app = ApplicationFactory()
        c = self._warm(staff)
        client_for(admin).post(reverse("ops-permit-create", kwargs={"pk": app.id}), {"permit_type": "building"}, format="json")
        assert get(c, QUEUE)["X-Cache"] == "MISS"

    def test_orm_write_outside_api_invalidates(self, staff):
        """Admin-site edits go through the ORM, not the API; the signal still catches them."""
        app = ApplicationFactory()
        c = self._warm(staff)
        PermitFactory(application=app)
        assert get(c, QUEUE)["X-Cache"] == "MISS"
        get(c, QUEUE)
        app.delete()
        assert get(c, QUEUE)["X-Cache"] == "MISS"

    def test_read_does_not_invalidate(self, staff, admin):
        app = ApplicationFactory()
        c = self._warm(staff)
        client_for(admin).get(reverse("ops-application", kwargs={"pk": app.id}))
        assert get(c, QUEUE)["X-Cache"] == "HIT"


class TestResilience:
    def test_cache_outage_degrades_to_uncached(self, staff):
        from unittest import mock

        ApplicationFactory()
        with mock.patch("applications.cache.cache.get", side_effect=ConnectionError("redis down")), mock.patch(
            "applications.cache.cache.set", side_effect=ConnectionError("redis down")
        ), mock.patch("applications.cache.cache.add", side_effect=ConnectionError("redis down")):
            res = client_for(staff).get(QUEUE)
        assert res.status_code == 200 and res.data["count"] == 1
