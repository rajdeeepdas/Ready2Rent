"""Small request/response middleware used in every environment."""

from django.http import JsonResponse

LIVEZ_PATH = "/api/livez/"


class LivenessMiddleware:
    """
    Answers the liveness probe before any other middleware runs. Platform health checkers
    call it with internal Host headers and plain HTTP, which ALLOWED_HOSTS validation and the
    HTTPS redirect would otherwise reject. The response carries no data, so skipping those
    checks for this one path exposes nothing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == LIVEZ_PATH and request.method in ("GET", "HEAD"):
            return JsonResponse({"status": "ok"})
        return self.get_response(request)


class ApiNoStoreMiddleware:
    """
    API responses are per-user and must never be stored by a shared cache: the production
    frontend host proxies /api to the backend and could otherwise cache one user's data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, private"
        return response
