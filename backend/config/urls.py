from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Path comes from DJANGO_ADMIN_URL so production does not expose the well-known /admin/.
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/", include("core.urls")),
    path("api/auth/", include("accounts.urls")),
    # Two surfaces, separated at the routing level. Each URLconf's views require the role.
    path("api/homeowner/", include("applications.urls_homeowner")),
    path("api/ops/", include("applications.urls_ops")),
]

# Uploaded documents are NEVER served as public static files (not even in DEBUG).
# They are streamed through authenticated, ownership-checked download views.
