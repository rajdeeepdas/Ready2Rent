"""
Milestone 2: authentication, cookies, CSRF, role routing, escalation prevention, throttling.
All requests go through a CSRF-enforcing APIClient so the cookie-authenticated endpoints
are exercised exactly as a browser would hit them.
"""

import datetime as dt

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User, UserRole
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-and-l0ng-passw0rd!"
COOKIE = settings.AUTH_COOKIE["name"]


class BrowserLikeClient(APIClient):
    """CSRF-enforcing client that, like the SPA, sends the CSRF token on login and register.
    Refresh and logout are left alone so tests can prove those reject a missing token."""

    AUTO_CSRF_PATHS = ("/api/auth/login/", "/api/auth/register/")

    def post(self, path, data=None, format=None, content_type=None, follow=False, **extra):
        if path in self.AUTO_CSRF_PATHS and "HTTP_X_CSRFTOKEN" not in extra:
            extra.update(csrf_headers(self))
        return super().post(path, data, format=format, content_type=content_type, follow=follow, **extra)


@pytest.fixture
def api():
    return BrowserLikeClient(enforce_csrf_checks=True)


def csrf_headers(client) -> dict:
    """Prime the csrftoken cookie and return the header a browser would send."""
    client.get(reverse("auth-csrf"))
    return {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}


def login(client, email, password=PASSWORD):
    return client.post(reverse("auth-login"), {"email": email, "password": password}, format="json")


def bearer(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.fixture
def homeowner_user(db):
    return UserFactory(role=UserRole.HOMEOWNER, password=PASSWORD)


@pytest.fixture
def staff_user(db):
    return UserFactory(role=UserRole.STAFF, password=PASSWORD)


@pytest.fixture
def admin_user(db):
    return UserFactory(role=UserRole.ADMIN, password=PASSWORD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
class TestRegister:
    def test_creates_homeowner_and_logs_in(self, api):
        res = api.post(
            reverse("auth-register"),
            {"email": "New.Person@Example.COM", "password": PASSWORD, "first_name": "New", "last_name": "Person"},
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["user"]["email"] == "new.person@example.com"  # normalized
        assert res.data["user"]["role"] == "homeowner"
        assert "access" in res.data and "refresh" not in res.data
        cookie = res.cookies[COOKIE]
        assert cookie["httponly"] and cookie["path"] == "/api/auth/" and cookie["samesite"] == "Lax"
        assert "csrftoken" in res.cookies

    def test_role_and_flags_cannot_be_escalated(self, api):
        res = api.post(
            reverse("auth-register"),
            {
                "email": "sneaky@example.com", "password": PASSWORD, "first_name": "S", "last_name": "N",
                "role": "admin", "is_staff": True, "is_superuser": True,
            },
            format="json",
        )
        assert res.status_code == 201
        u = User.objects.get(email="sneaky@example.com")
        assert u.role == UserRole.HOMEOWNER and not u.is_staff and not u.is_superuser

    def test_duplicate_email_case_insensitive(self, api, homeowner_user):
        res = api.post(
            reverse("auth-register"),
            {"email": homeowner_user.email.upper(), "password": PASSWORD, "first_name": "A", "last_name": "B"},
            format="json",
        )
        assert res.status_code == 400 and "email" in res.data

    @pytest.mark.parametrize("bad", ["short", "password123", "12345678"])
    def test_django_password_validators_apply(self, api, bad):
        res = api.post(
            reverse("auth-register"),
            {"email": "x@example.com", "password": bad, "first_name": "A", "last_name": "B"},
            format="json",
        )
        assert res.status_code == 400
        assert not User.objects.filter(email="x@example.com").exists()

    def test_password_similar_to_email_rejected(self, api):
        res = api.post(
            reverse("auth-register"),
            {"email": "jonathan.smithers@example.com", "password": "jonathan.smithers", "first_name": "J", "last_name": "S"},
            format="json",
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestLogin:
    def test_success_sets_cookie_and_returns_access(self, api, homeowner_user):
        res = login(api, homeowner_user.email.upper())  # case-insensitive
        assert res.status_code == 200
        assert res.data["user"]["id"] == str(homeowner_user.id)
        assert "refresh" not in res.data
        assert res.cookies[COOKIE]["httponly"]
        AccessToken(res.data["access"])  # parses & verifies

    def test_failure_modes_are_indistinguishable(self, api, homeowner_user):
        inactive = UserFactory(role=UserRole.HOMEOWNER, password=PASSWORD, is_active=False)
        responses = [
            login(api, "nobody@example.com"),
            login(api, homeowner_user.email, "wrong-password"),
            login(api, inactive.email),
        ]
        bodies = {(r.status_code, tuple(sorted(r.data.items()))) for r in responses}
        assert len(bodies) == 1, bodies
        code, body = next(iter(bodies))
        assert code == 401 and dict(body) == {"detail": "Invalid email or password."}
        assert all(COOKIE not in r.cookies for r in responses)

    def test_missing_fields_is_400(self, api):
        res = api.post(reverse("auth-login"), {"email": "a@b.com"}, format="json")
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
class TestMe:
    def test_requires_auth(self, api):
        assert api.get(reverse("auth-me")).status_code == 401

    def test_get_and_patch_profile(self, api, homeowner_user):
        access = login(api, homeowner_user.email).data["access"]
        res = api.get(reverse("auth-me"), **bearer(access))
        assert res.status_code == 200 and res.data["email"] == homeowner_user.email
        res = api.patch(reverse("auth-me"), {"first_name": "Renamed", "phone": "403-555-0100"}, format="json", **bearer(access))
        assert res.status_code == 200 and res.data["first_name"] == "Renamed"

    def test_cannot_escalate_via_patch(self, api, homeowner_user):
        access = login(api, homeowner_user.email).data["access"]
        res = api.patch(
            reverse("auth-me"),
            {"role": "admin", "is_staff": True, "is_superuser": True, "email": "other@example.com"},
            format="json",
            **bearer(access),
        )
        assert res.status_code == 200
        homeowner_user.refresh_from_db()
        assert homeowner_user.role == UserRole.HOMEOWNER
        assert not homeowner_user.is_staff and not homeowner_user.is_superuser
        assert homeowner_user.email != "other@example.com"

    def test_deactivated_user_token_is_rejected(self, api, homeowner_user):
        access = login(api, homeowner_user.email).data["access"]
        homeowner_user.is_active = False
        homeowner_user.save()
        assert api.get(reverse("auth-me"), **bearer(access)).status_code == 401


# ---------------------------------------------------------------------------
# Refresh (cookie + CSRF)
# ---------------------------------------------------------------------------
class TestRefresh:
    def test_rotates_and_blacklists_old_token(self, api, homeowner_user):
        login(api, homeowner_user.email)
        old_cookie = api.cookies[COOKIE].value
        res = api.post(reverse("auth-refresh"), **csrf_headers(api))
        assert res.status_code == 200 and "access" in res.data
        new_cookie = res.cookies[COOKIE].value
        assert new_cookie and new_cookie != old_cookie

        # Replaying the old refresh token must fail (blacklisted after rotation).
        api.cookies[COOKIE] = old_cookie
        res = api.post(reverse("auth-refresh"), **csrf_headers(api))
        assert res.status_code == 401
        assert res.cookies[COOKIE]["max-age"] == 0  # cleared

    def test_requires_csrf_token(self, api, homeowner_user):
        login(api, homeowner_user.email)
        res = api.post(reverse("auth-refresh"))  # no X-CSRFToken header
        assert res.status_code == 403
        assert "CSRF" in res.data["detail"]

    def test_bad_origin_rejected(self, api, homeowner_user):
        login(api, homeowner_user.email)
        headers = csrf_headers(api)
        res = api.post(reverse("auth-refresh"), HTTP_ORIGIN="https://evil.example", **headers)
        assert res.status_code == 403

    def test_without_cookie_is_401(self, api):
        res = api.post(reverse("auth-refresh"), **csrf_headers(api))
        assert res.status_code == 401

    def test_deactivated_user_cannot_refresh(self, api, homeowner_user):
        login(api, homeowner_user.email)
        homeowner_user.is_active = False
        homeowner_user.save()
        res = api.post(reverse("auth-refresh"), **csrf_headers(api))
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class TestLogout:
    def test_blacklists_and_clears_cookie(self, api, homeowner_user):
        login(api, homeowner_user.email)
        refresh_value = api.cookies[COOKIE].value
        res = api.post(reverse("auth-logout"), **csrf_headers(api))
        assert res.status_code == 204
        assert res.cookies[COOKIE]["max-age"] == 0
        # The refresh token can no longer be used.
        api.cookies[COOKIE] = refresh_value
        assert api.post(reverse("auth-refresh"), **csrf_headers(api)).status_code == 401

    def test_works_with_expired_access_token(self, api, homeowner_user):
        login(api, homeowner_user.email)
        expired = AccessToken.for_user(homeowner_user)
        expired.set_exp(from_time=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2))
        res = api.post(reverse("auth-logout"), **csrf_headers(api), **bearer(str(expired)))
        assert res.status_code == 204 and res.cookies[COOKIE]["max-age"] == 0

    def test_clears_cookie_even_if_token_is_garbage(self, api):
        api.cookies[COOKIE] = "not-a-jwt"
        res = api.post(reverse("auth-logout"), **csrf_headers(api))
        assert res.status_code == 204 and res.cookies[COOKIE]["max-age"] == 0

    def test_requires_csrf(self, api, homeowner_user):
        login(api, homeowner_user.email)
        assert api.post(reverse("auth-logout")).status_code == 403


# ---------------------------------------------------------------------------
# Role routing between the two surfaces
# ---------------------------------------------------------------------------
class TestSurfaces:
    def test_anonymous_gets_401_everywhere(self, api):
        assert api.get(reverse("homeowner-ping")).status_code == 401
        assert api.get(reverse("ops-ping")).status_code == 401

    def test_homeowner_never_reaches_ops(self, api, homeowner_user):
        access = login(api, homeowner_user.email).data["access"]
        assert api.get(reverse("homeowner-ping"), **bearer(access)).status_code == 200
        assert api.get(reverse("ops-ping"), **bearer(access)).status_code == 403

    @pytest.mark.parametrize("fixture", ["staff_user", "admin_user"])
    def test_ops_roles_reach_ops_not_homeowner(self, api, fixture, request):
        user = request.getfixturevalue(fixture)
        access = login(api, user.email).data["access"]
        assert api.get(reverse("ops-ping"), **bearer(access)).status_code == 200
        assert api.get(reverse("homeowner-ping"), **bearer(access)).status_code == 403


# ---------------------------------------------------------------------------
# Django admin site: only admin-role accounts
# ---------------------------------------------------------------------------
class TestAdminSiteConsistency:
    @pytest.mark.parametrize("role,expected", [("homeowner", False), ("staff", False), ("admin", True)])
    def test_is_staff_derived_from_role(self, role, expected):
        u = UserFactory(role=role, is_staff=not expected)  # try to set it wrong
        u.refresh_from_db()
        assert u.is_staff is expected

    def test_update_fields_save_keeps_is_staff_consistent(self, staff_user):
        User.objects.filter(pk=staff_user.pk).update(is_staff=True)  # bypass save()
        staff_user.refresh_from_db()
        assert staff_user.is_staff is True
        staff_user.save(update_fields=["first_name"])
        staff_user.refresh_from_db()
        assert staff_user.is_staff is False

    def test_staff_role_cannot_enter_admin_site(self, client, staff_user):
        client.force_login(staff_user)
        res = client.get("/admin/")
        assert res.status_code == 302 and "/admin/login/" in res["Location"]

    def test_admin_role_can_enter_admin_site(self, client, admin_user):
        client.force_login(admin_user)
        assert client.get("/admin/").status_code == 200

    def test_superuser_is_admin_role(self):
        u = User.objects.create_superuser("root@example.com", PASSWORD)
        assert u.role == UserRole.ADMIN and u.is_staff


# ---------------------------------------------------------------------------
# Throttling (Redis-backed)
# ---------------------------------------------------------------------------
class TestThrottle:
    def test_login_rate_limited(self, api, homeowner_user, settings):
        assert settings.CACHES["default"]["BACKEND"] == "django_redis.cache.RedisCache"
        for _ in range(10):
            assert login(api, homeowner_user.email, "wrong").status_code == 401
        res = login(api, homeowner_user.email, "wrong")
        assert res.status_code == 429
        assert "Retry-After" in res

    def test_register_rate_limited(self, api):
        for i in range(10):
            api.post(reverse("auth-register"), {"email": f"u{i}@x.com"}, format="json")
        res = api.post(reverse("auth-register"), {"email": "u11@x.com"}, format="json")
        assert res.status_code == 429
