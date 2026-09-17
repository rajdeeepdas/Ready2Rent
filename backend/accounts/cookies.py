"""
Refresh-token cookie helpers and explicit CSRF enforcement.

DRF views are csrf_exempt at the Django level (CSRF is normally enforced only by
SessionAuthentication). The refresh and logout endpoints authenticate with a cookie,
so they must run Django's CSRF check themselves; enforce_csrf() does that, including
the Origin / Referer validation against CSRF_TRUSTED_ORIGINS.
"""

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.exceptions import PermissionDenied


def set_refresh_cookie(response, refresh_token: str) -> None:
    c = settings.AUTH_COOKIE
    response.set_cookie(
        key=c["name"],
        value=refresh_token,
        max_age=c["max_age"],
        path=c["path"],
        domain=c["domain"],
        secure=c["secure"],
        httponly=True,
        samesite=c["samesite"],
    )


def clear_refresh_cookie(response) -> None:
    c = settings.AUTH_COOKIE
    response.delete_cookie(key=c["name"], path=c["path"], domain=c["domain"], samesite=c["samesite"])


def get_refresh_cookie(request) -> str | None:
    return request.COOKIES.get(settings.AUTH_COOKIE["name"])


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        # Return the reason instead of an HttpResponseForbidden so the caller can raise.
        return reason


def enforce_csrf(request) -> None:
    """Raise PermissionDenied unless the request carries a valid CSRF token + acceptable origin."""

    def _noop(_request):
        return None

    check = _CSRFCheck(_noop)
    http_request = getattr(request, "_request", request)
    check.process_request(http_request)
    reason = check.process_view(http_request, None, (), {})
    if reason:
        raise PermissionDenied(f"CSRF failed: {reason}")
