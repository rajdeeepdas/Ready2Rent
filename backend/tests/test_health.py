"""Health endpoints: public liveness vs. staff-only detailed check."""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tests.api_helpers import client_for

pytestmark = pytest.mark.django_db

LIVEZ = reverse("livez")
HEALTH = reverse("health")


class TestLiveness:
    def test_anonymous_ok_and_minimal(self):
        res = APIClient().get(LIVEZ)
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}  # no versions, dependencies, or timestamps

    def test_homeowner_ok(self, homeowner):
        assert client_for(homeowner).get(LIVEZ).status_code == 200

    def test_answers_despite_unknown_host(self):
        """Platform probes use internal Host headers; the probe must not 400 on them."""
        res = APIClient().get(LIVEZ, HTTP_HOST="10.0.0.7:8000")
        assert res.status_code == 200 and res.json() == {"status": "ok"}

    def test_other_paths_still_validate_host(self):
        res = APIClient().get("/api/health/", HTTP_HOST="evil.example")
        assert res.status_code == 400  # DisallowedHost


class TestDetailedHealth:
    def test_anonymous_rejected(self):
        res = APIClient().get(HEALTH)
        assert res.status_code == 401  # unauthenticated, same as every protected endpoint
        assert "checks" not in res.data

    def test_homeowner_forbidden(self, homeowner):
        res = client_for(homeowner).get(HEALTH)
        assert res.status_code == 403
        assert "checks" not in res.data

    @pytest.mark.parametrize("fixture", ["staff", "admin"])
    def test_ops_roles_get_full_report(self, fixture, request):
        user = request.getfixturevalue(fixture)
        res = client_for(user).get(HEALTH)
        assert res.status_code == 200
        assert res.data["status"] == "ok"
        assert res.data["checks"] == {"database": "ok", "redis": "ok"}
        assert "django" in res.data["version"] and "timestamp" in res.data

    def test_degraded_returns_503_for_staff(self, staff):
        with mock.patch("core.views.get_redis_connection", side_effect=ConnectionError("down")):
            res = client_for(staff).get(HEALTH)
        assert res.status_code == 503
        assert res.data["status"] == "degraded"
        assert res.data["checks"]["redis"].startswith("error:")
        assert res.data["checks"]["database"] == "ok"

    def test_degraded_still_hidden_from_homeowner(self, homeowner):
        with mock.patch("core.views.get_redis_connection", side_effect=ConnectionError("down")):
            res = client_for(homeowner).get(HEALTH)
        assert res.status_code == 403
