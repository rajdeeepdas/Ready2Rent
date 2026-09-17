"""
Django settings for Ready2Rent.

Everything environment-specific comes from environment variables (loaded from the
repo-root .env locally; set directly by the host in production). Nothing here is
hardcoded to a URL, host, or secret.
"""

from datetime import timedelta
from pathlib import Path

import environ

from .storage import build_storages

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    # Reverse-proxy awareness (set only when behind a trusted proxy / load balancer)
    DJANGO_NUM_PROXIES=(int, 0),
    DJANGO_USE_X_FORWARDED_PROTO=(bool, False),
    # Auth cookies
    AUTH_COOKIE_SECURE=(bool, None),  # None -> derived from DEBUG
    AUTH_COOKIE_SAMESITE=(str, "Lax"),
    AUTH_COOKIE_DOMAIN=(str, None),
    ACCESS_TOKEN_MINUTES=(int, 30),
    REFRESH_TOKEN_DAYS=(int, 7),
    # Milestone 5
    CELERY_BROKER_URL=(str, None),  # None -> derived from REDIS_URL (db 1)
    CELERY_TASK_ALWAYS_EAGER=(bool, False),  # run tasks inline (tests / no worker)
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    DEFAULT_FROM_EMAIL=(str, "Ready2Rent <no-reply@ready2rent.local>"),
    EMAIL_HOST=(str, ""),
    EMAIL_PORT=(int, 587),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    EMAIL_USE_TLS=(bool, True),
    OPS_QUEUE_CACHE_SECONDS=(int, 60),
    FRONTEND_URL=(str, "http://localhost:5173"),
    # Milestone 7: production hardening
    DJANGO_ADMIN_URL=(str, "admin/"),
    SECURE_SSL_REDIRECT=(bool, True),  # only applied when DEBUG is off
    SECURE_HSTS_SECONDS=(int, 31536000),  # only applied when DEBUG is off
    SECURE_HSTS_INCLUDE_SUBDOMAINS=(bool, False),
    SECURE_HSTS_PRELOAD=(bool, False),
    MAX_OTHER_DOCUMENTS=(int, 25),
)

# Local development: read the shared .env at the repo root (gitignored).
# In production the host injects env vars and this file simply won't exist.
_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    environ.Env.read_env(str(_env_file))

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
# Render injects the service's public hostname; accept it without hardcoding the URL.
if env("RENDER_EXTERNAL_HOSTNAME", default=None):
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))

if not DEBUG:
    from .security import validate_secret_key

    validate_secret_key(SECRET_KEY)  # refuse to boot production with a weak key

# Django admin lives at an env-configurable path so it is not at the well-known /admin/.
ADMIN_URL = env("DJANGO_ADMIN_URL").strip("/") + "/"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",  # approved auth infrastructure tables
    "corsheaders",
    # Project
    "core",
    "accounts",
    "applications",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "core.middleware.LivenessMiddleware",  # first: answers /api/livez/ before host/HTTPS checks
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.ApiNoStoreMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # must sit above CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    # Serves collected static files (Django admin CSS/JS) in production. Locally runserver
    # serves them itself, and STATIC_ROOT only exists after collectstatic.
    MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")  # right after SecurityMiddleware

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL only: no SQLite fallback, so dev matches prod)
# ---------------------------------------------------------------------------
if env("DATABASE_URL", default=None):
    # Hosted platforms (Render/Railway/Fly) provide a single DATABASE_URL.
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST", default="localhost"),
            "PORT": env("POSTGRES_PORT", default="5432"),
        }
    }
# Reuse connections, but verify them first: a managed pooler (Supabase Supavisor) may close
# idle connections, e.g. while the free web service is asleep.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 10

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Cache (Redis). Used for the health check now; ops-queue caching in Milestone 5.
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 2,
            "SOCKET_TIMEOUT": 2,
        },
        "KEY_PREFIX": "r2r",
    }
}

# Ops queue cache: entries live at most this long; every write to an application or its
# children bumps a version key so readers never see stale rows for longer than one request.
OPS_QUEUE_CACHE_SECONDS = env("OPS_QUEUE_CACHE_SECONDS")

# ---------------------------------------------------------------------------
# Celery (Redis broker). Tasks: staff notification on new leads, homeowner emails.
# ---------------------------------------------------------------------------
def _redis_db(url: str, db: int) -> str:
    base = url[: url.rfind("/")] if url.count("/") >= 3 else url
    return f"{base}/{db}"


CELERY_BROKER_URL = env("CELERY_BROKER_URL") or _redis_db(REDIS_URL, 1)
CELERY_RESULT_BACKEND = None  # fire-and-forget notifications; nothing reads results
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True  # a task is acked after it finishes, so a crash mid-task re-queues it
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "America/Edmonton"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# Periodic jobs, run when a worker is started with -B (embedded beat).
CELERY_BEAT_SCHEDULE = {
    "flush-expired-refresh-tokens": {
        "task": "accounts.flush_expired_tokens",
        "schedule": 60 * 60 * 24,  # daily
    },
}

# ---------------------------------------------------------------------------
# Email. Console backend locally (messages print in the Celery worker's terminal).
# Production SMTP values are env-provided and require Gate 4 approval.
# ---------------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
_email_backend = env("EMAIL_BACKEND")
_email_options = {}
if _email_backend.endswith("smtp.EmailBackend"):
    _email_options = {
        "host": env("EMAIL_HOST"),
        "port": env("EMAIL_PORT"),
        "username": env("EMAIL_HOST_USER"),
        "password": env("EMAIL_HOST_PASSWORD"),
        "use_tls": env("EMAIL_USE_TLS"),
    }
# Django 6.x MAILERS (replaces the deprecated EMAIL_* settings). Django's test runner
# swaps every mailer here for the in-memory backend automatically.
MAILERS = {"default": {"BACKEND": _email_backend, "OPTIONS": _email_options}}
FRONTEND_URL = env("FRONTEND_URL").rstrip("/")  # used for links inside emails

# ---------------------------------------------------------------------------
# Auth / passwords
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    # JWT only. No SessionAuthentication: the SPA never authenticates with the session cookie.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    # Throttling is backed by the default cache (Redis), so limits are shared across
    # API processes. It is abuse *reduction*, not brute-force protection: see DECISIONS.md.
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "10/min",
        "auth_register": "10/min",
        "auth_refresh": "60/min",
        # Per authenticated user: caps disk use and staff-notification volume from one account.
        "intake": "10/day",
        "uploads": "60/hour",
    },
    # Number of trusted proxies in front of the app. When > 0, DRF derives the client IP
    # for throttling from X-Forwarded-For (rightmost N entries stripped). 0 locally.
    "NUM_PROXIES": env("DJANGO_NUM_PROXIES") or None,
}

# ---------------------------------------------------------------------------
# Auth: JWT. Access token lives in SPA memory only; refresh token in an HttpOnly cookie.
# ---------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("ACCESS_TOKEN_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("REFRESH_TOKEN_DAYS")),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

_cookie_secure = env("AUTH_COOKIE_SECURE")
if _cookie_secure is None:
    _cookie_secure = not DEBUG

AUTH_COOKIE = {
    "name": "r2r_refresh",
    "path": "/api/auth/",  # the browser only sends it to auth endpoints
    "secure": _cookie_secure,
    "samesite": env("AUTH_COOKIE_SAMESITE"),
    "domain": env("AUTH_COOKIE_DOMAIN"),
    "max_age": int(SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
}

# ---------------------------------------------------------------------------
# CSRF: cookie-authenticated endpoints (refresh, logout) enforce Django's CSRF check,
# which also validates the Origin header against the host / trusted origins.
# ---------------------------------------------------------------------------
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to send X-CSRFToken
CSRF_COOKIE_SECURE = _cookie_secure
CSRF_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE")
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
# Explicit origins only. Empty locally because the Vite proxy makes requests same-origin.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# ---------------------------------------------------------------------------
# CORS. Normally unused: the SPA reaches the API same-origin through a proxy (Vite locally,
# the frontend host in production). Only needed for the app./api. subdomain deployment
# option. Explicit origins only; CORS_ALLOW_ALL_ORIGINS is never set.
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Reverse proxy / HTTPS awareness (production only, behind a trusted proxy)
# ---------------------------------------------------------------------------
if env("DJANGO_USE_X_FORWARDED_PROTO"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Off by default: behind the frontend's /api proxy the Host header stays the backend's own
# hostname, and the browser's Origin is trusted explicitly through CSRF_TRUSTED_ORIGINS.
USE_X_FORWARDED_HOST = env.bool("DJANGO_USE_X_FORWARDED_HOST", default=False)

# Always-on headers (Django defaults, stated explicitly so they are reviewable)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
    # Platform probes call the liveness endpoint over plain HTTP inside the network.
    SECURE_REDIRECT_EXEMPT = [r"^api/livez/$"]
    SECURE_HSTS_SECONDS = env("SECURE_HSTS_SECONDS")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env("SECURE_HSTS_INCLUDE_SUBDOMAINS")
    SECURE_HSTS_PRELOAD = env("SECURE_HSTS_PRELOAD")

# ---------------------------------------------------------------------------
# i18n / time
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-ca"
TIME_ZONE = "America/Edmonton"  # Calgary
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
# Local upload directory (development and tests). Production uses Supabase Storage; see STORAGES below.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
MAX_UPLOAD_MB = env.int("MAX_UPLOAD_MB", default=20)
MAX_OTHER_DOCUMENTS = env("MAX_OTHER_DOCUMENTS")  # extra "other" uploads allowed per application
# DATA_UPLOAD_MAX_MEMORY_SIZE stays at Django's 2.5 MB default. It limits non-file request
# bodies (JSON); uploaded files stream to disk and are capped separately by MAX_UPLOAD_MB.
FILE_UPLOAD_PERMISSIONS = 0o640

# Uploads: local filesystem by default; a private Supabase Storage bucket (S3 API) when
# SUPABASE_S3_ENDPOINT_URL is set. See config/storage.py.
_supabase_endpoint = env("SUPABASE_S3_ENDPOINT_URL", default="")
STORAGES = build_storages(
    debug=DEBUG,
    s3={
        "endpoint_url": _supabase_endpoint,
        "region_name": env("SUPABASE_S3_REGION", default=""),
        "access_key": env("SUPABASE_S3_ACCESS_KEY_ID", default=""),
        "secret_key": env("SUPABASE_S3_SECRET_ACCESS_KEY", default=""),
        "bucket_name": env("SUPABASE_STORAGE_BUCKET", default="documents"),
    }
    if _supabase_endpoint
    else None,
)
