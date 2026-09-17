"""Milestone 7: behaviour the production deploy relies on."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from tests.api_helpers import client_for
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestApiNotCacheable:
    """The frontend host proxies /api; per-user responses must never be stored by it."""

    @pytest.mark.parametrize("name", ["homeowner-applications", "auth-me"])
    def test_authenticated_api_responses_are_no_store(self, homeowner, name):
        res = client_for(homeowner).get(reverse(name))
        assert res.status_code == 200
        assert "no-store" in res["Cache-Control"] and "private" in res["Cache-Control"]

    def test_error_and_auth_responses_are_no_store(self):
        assert "no-store" in APIClient().get(reverse("homeowner-applications"))["Cache-Control"]
        assert "no-store" in APIClient().get(reverse("auth-csrf"))["Cache-Control"]

    def test_non_api_paths_untouched(self, client):
        res = client.get("/not-an-api-path/")
        assert "Cache-Control" not in res


class TestAdminRoleIsSuperuser:
    @pytest.mark.parametrize("role,expected", [("homeowner", False), ("staff", False), ("admin", True)])
    def test_superuser_flag_follows_role(self, role, expected):
        u = UserFactory(role=role, is_superuser=not expected)
        u.refresh_from_db()
        assert u.is_superuser is expected and u.is_staff is expected

    def test_demotion_revokes_superuser(self):
        u = User.objects.create_superuser("boss@example.com", "Sm0ke-Test-Passw0rd!")
        assert u.is_superuser
        u.role = UserRole.STAFF
        u.save(update_fields=["role"])
        u.refresh_from_db()
        assert not u.is_superuser and not u.is_staff

    def test_api_cannot_grant_superuser(self, homeowner):
        client_for(homeowner).patch(reverse("auth-me"), {"is_superuser": True, "role": "admin"}, format="json")
        homeowner.refresh_from_db()
        assert not homeowner.is_superuser and homeowner.role == UserRole.HOMEOWNER


class TestTokenCleanupTask:
    def test_flush_task_removes_expired_tokens(self, homeowner):
        import datetime as dt

        from django.utils import timezone
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        from accounts.tasks import flush_expired_tokens

        now = timezone.now()
        OutstandingToken.objects.create(user=homeowner, jti="old", token="x", created_at=now - dt.timedelta(days=30), expires_at=now - dt.timedelta(days=1))
        OutstandingToken.objects.create(user=homeowner, jti="live", token="y", created_at=now, expires_at=now + dt.timedelta(days=7))
        flush_expired_tokens()
        assert list(OutstandingToken.objects.values_list("jti", flat=True)) == ["live"]

    def test_task_is_scheduled_daily(self, settings):
        entry = settings.CELERY_BEAT_SCHEDULE["flush-expired-refresh-tokens"]
        assert entry["task"] == "accounts.flush_expired_tokens" and entry["schedule"] == 86400


class TestMediaRootFromEnv:
    def test_media_root_is_a_path(self, settings):
        from pathlib import Path

        assert isinstance(settings.MEDIA_ROOT, Path)
