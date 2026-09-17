"""
Shared pytest fixtures. Tests run against a throwaway PostgreSQL database
(test_<POSTGRES_DB>) created by pytest-django, never against SQLite, so every
constraint and lock behaves exactly as in production.
"""

import pytest

from accounts.models import UserRole
from applications.enums import SuiteType
from applications.models import Application, Property, Suite
from tests.factories import ApplicationFactory, PropertyFactory, SuiteFactory, UserFactory


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """PBKDF2 is deliberately slow (~100ms+/hash). Tests create many users; use MD5 here only."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def eager_celery(settings):
    """Run tasks inline in tests: no worker, no broker round-trip, exceptions surface."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    from config.celery import app

    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def isolated_redis_cache(settings):
    """Keep Redis-backed caching/throttling in tests, but on a separate Redis DB with its
    own key prefix, cleared before every test so throttle counters never leak."""
    import copy

    from django.core.cache import cache

    caches = copy.deepcopy(settings.CACHES)
    loc = caches["default"]["LOCATION"]
    caches["default"]["LOCATION"] = loc[: loc.rfind("/")] + "/15"
    caches["default"]["KEY_PREFIX"] = "r2r-test"
    settings.CACHES = caches
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def homeowner(db):
    return UserFactory(role=UserRole.HOMEOWNER)


@pytest.fixture
def other_homeowner(db):
    return UserFactory(role=UserRole.HOMEOWNER)


@pytest.fixture
def staff(db):
    return UserFactory(role=UserRole.STAFF)


@pytest.fixture
def admin(db):
    return UserFactory(role=UserRole.ADMIN)


@pytest.fixture
def prop(homeowner) -> Property:
    return PropertyFactory(owner=homeowner)


@pytest.fixture
def suite(prop) -> Suite:
    return SuiteFactory(property=prop, suite_type=SuiteType.LEGALIZE_EXISTING)


@pytest.fixture
def application(homeowner, prop, suite) -> Application:
    return ApplicationFactory(homeowner=homeowner, property=prop, suite=suite)
