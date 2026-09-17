import logging

from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .cookies import clear_refresh_cookie, enforce_csrf, get_refresh_cookie, set_refresh_cookie
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

logger = logging.getLogger(__name__)


def _issue_tokens_response(request, user, http_status=status.HTTP_200_OK) -> Response:
    """Access token in the body (SPA keeps it in memory); refresh token only in the cookie."""
    refresh = RefreshToken.for_user(user)
    response = Response(
        {"access": str(refresh.access_token), "user": UserSerializer(user).data},
        status=http_status,
    )
    set_refresh_cookie(response, str(refresh))
    # Make sure the CSRF cookie is (re)issued alongside the refresh cookie.
    get_token(request._request)
    return response


class CsrfView(APIView):
    """GET: sets the csrftoken cookie so the SPA can call refresh/logout on a cold load."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class RegisterView(APIView):
    """JSON only + CSRF/Origin check: a cross-site HTML form cannot create an account and
    silently sign the victim into it (login CSRF)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    def post(self, request):
        enforce_csrf(request)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return _issue_tokens_response(request, user, http_status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """JSON only + CSRF/Origin check. Without this a malicious page could auto-submit a form
    that logs the victim into the attacker's account, so the victim's uploads (land title,
    photos) would land in an account the attacker controls."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    def post(self, request):
        enforce_csrf(request)
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            # Field-level errors (missing fields) are 400; credential failures are 401
            # with one generic message regardless of cause.
            if "detail" in serializer.errors:
                return Response(
                    {"detail": LoginSerializer.GENERIC_ERROR}, status=status.HTTP_401_UNAUTHORIZED
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return _issue_tokens_response(request, serializer.validated_data["user"])


class RefreshView(APIView):
    """Cookie-authenticated: requires a valid CSRF token. Rotates the refresh token and
    blacklists the previous one."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_refresh"

    def post(self, request):
        enforce_csrf(request)
        raw = get_refresh_cookie(request)
        if not raw:
            return Response({"detail": "No refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            old = RefreshToken(raw)  # validates signature, expiry, and blacklist
            user_id = old.get("user_id")
            from .models import User

            user = User.objects.filter(pk=user_id, is_active=True).first()
            if user is None:
                raise TokenError("User inactive or missing.")
            old.blacklist()
        except TokenError:
            response = Response({"detail": "Refresh token invalid."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_refresh_cookie(response)
            return response
        return _issue_tokens_response(request, user)


class LogoutView(APIView):
    """Works even when the access token has expired (no auth required). Blacklists the
    refresh token if it can, and clears the cookie unconditionally."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]

    def post(self, request):
        enforce_csrf(request)
        raw = get_refresh_cookie(request)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError as exc:
                # Already expired / blacklisted / malformed: nothing to revoke.
                logger.info("Logout: refresh token not blacklisted (%s)", exc)
            except Exception:  # noqa: BLE001 — DB down etc.; still clear the cookie
                logger.exception("Logout: blacklisting failed")
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
