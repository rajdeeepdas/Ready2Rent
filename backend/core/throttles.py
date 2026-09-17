"""Throttles shared across apps. Counters live in the default cache (Redis)."""

from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import ScopedRateThrottle


class ScopedWriteThrottle(ScopedRateThrottle):
    """
    Like ScopedRateThrottle, but only counts unsafe methods (POST/PUT/PATCH/DELETE).
    Lets a view that serves both a list (GET) and a create (POST) throttle only creation.
    Authenticated requests are keyed by user id, anonymous ones by client IP.
    """

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
