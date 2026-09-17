import logging

import django
from django.db import connection
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsOps

logger = logging.getLogger(__name__)


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return "ok"
    except Exception as exc:  # noqa: BLE001 (a health check must never raise)
        logger.warning("Database health check failed: %s", exc)
        return f"error: {exc.__class__.__name__}"


def _check_redis() -> str:
    try:
        get_redis_connection("default").ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", exc)
        return f"error: {exc.__class__.__name__}"


class LivenessView(APIView):
    """
    GET /api/livez/

    Unauthenticated liveness probe for hosting platforms and container healthchecks.
    Says only that the API process is up; exposes no versions, dependencies, or timestamps.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class HealthView(APIView):
    """
    GET /api/health/

    Detailed dependency check for the internal ops tool: PostgreSQL, Redis, Django version.
    Staff and admin only (same role mechanism as the rest of the ops surface):
    anonymous -> 401, homeowner -> 403. Returns 200 when healthy, 503 when degraded.
    """

    permission_classes = [IsAuthenticated, IsOps]

    def get(self, request):
        checks = {"database": _check_database(), "redis": _check_redis()}
        healthy = all(value == "ok" for value in checks.values())
        payload = {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "version": {"django": django.get_version()},
            "timestamp": timezone.now().isoformat(),
        }
        return Response(
            payload,
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
