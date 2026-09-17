"""Startup guards for production configuration."""

from django.core.exceptions import ImproperlyConfigured

PLACEHOLDER_MARKERS = ("change-me", "changeme", "secret", "django-insecure")


def validate_secret_key(key: str) -> None:
    """
    Refuse to boot a production (DEBUG=False) process with a weak or placeholder SECRET_KEY.
    The key signs JWTs, sessions, and CSRF tokens: a guessable key means forgeable logins.
    """
    problems = []
    if not key:
        problems.append("it is empty")
    else:
        if len(key) < 50:
            problems.append("it is shorter than 50 characters")
        if len(set(key)) < 5:
            problems.append("it has fewer than 5 distinct characters")
        lowered = key.lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            problems.append("it looks like a placeholder")
    if problems:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not safe for production: " + ", ".join(problems) + ". "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
