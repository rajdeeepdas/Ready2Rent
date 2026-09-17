"""
Access matrix over EVERY API route, discovered from the URLconfs rather than listed by
hand, so a new endpoint cannot ship without the right role check.

DRF authenticates and checks permissions before it dispatches to a method handler, so a
GET is enough to prove the gate even on POST-only routes (a wrong role gets 403, never 405).
"""

import uuid

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from tests.api_helpers import client_for

pytestmark = pytest.mark.django_db

# Routes that are public by design.
PUBLIC = {"livez", "auth-csrf", "auth-register", "auth-login", "auth-refresh", "auth-logout"}
# Routes any authenticated user may reach.
ANY_AUTHENTICATED = {"auth-me"}


def _collect(resolver, prefix=""):
    """Yield (name, concrete_path) for every named pattern under /api/, filling UUID params."""
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _collect(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern) and p.name:
            path = prefix + str(p.pattern)
            for conv in ("pk", "doc_pk", "child_pk"):
                path = path.replace(f"<uuid:{conv}>", str(uuid.uuid4()))
            if path.startswith("api/"):
                yield p.name, "/" + path


ROUTES = sorted(set(_collect(get_resolver())))
HOMEOWNER_ROUTES = [(n, p) for n, p in ROUTES if p.startswith("/api/homeowner/")]
OPS_ROUTES = [(n, p) for n, p in ROUTES if p.startswith("/api/ops/") or n == "health"]
PROTECTED = [(n, p) for n, p in ROUTES if n not in PUBLIC]


def test_every_api_route_is_classified():
    """Fail loudly if a route appears that is neither public, any-authenticated, nor on a surface."""
    surfaces = {n for n, _ in HOMEOWNER_ROUTES} | {n for n, _ in OPS_ROUTES}
    unclassified = [n for n, _ in ROUTES if n not in PUBLIC | ANY_AUTHENTICATED | surfaces]
    assert unclassified == [], f"Classify these routes in test_access_matrix.py: {unclassified}"
    assert len(ROUTES) >= 30


@pytest.mark.parametrize("name,path", PROTECTED, ids=[n for n, _ in PROTECTED])
def test_anonymous_gets_401(name, path):
    res = APIClient().get(path)
    assert res.status_code == 401, (name, path, res.status_code)


@pytest.mark.parametrize("name,path", OPS_ROUTES, ids=[n for n, _ in OPS_ROUTES])
def test_homeowner_blocked_from_ops(homeowner, name, path):
    res = client_for(homeowner).get(path)
    assert res.status_code == 403, (name, path, res.status_code)


@pytest.mark.parametrize("name,path", HOMEOWNER_ROUTES, ids=[n for n, _ in HOMEOWNER_ROUTES])
@pytest.mark.parametrize("role", ["staff", "admin"])
def test_ops_roles_blocked_from_homeowner_surface(request, role, name, path):
    user = request.getfixturevalue(role)
    res = client_for(user).get(path)
    assert res.status_code == 403, (role, name, path, res.status_code)


@pytest.mark.parametrize("name,path", [(n, p) for n, p in ROUTES if n in PUBLIC], ids=[n for n, _ in ROUTES if n in PUBLIC])
def test_public_routes_never_401(name, path):
    """Public routes may answer 200/204/400/405, but never demand credentials."""
    res = APIClient().get(path)
    assert res.status_code != 401, (name, path, res.status_code)
