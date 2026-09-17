"""
Django admin smoke tests: every registered model's changelist, add form, and change form
render for an admin-role user, and the site is closed to everyone else. Catches broken
`list_display`, `autocomplete_fields`, inlines, and readonly configuration.
"""

import pytest
from django.contrib import admin as django_admin
from django.urls import reverse

from tests.factories import (
    ApplicationFactory,
    ComplianceItemFactory,
    DocumentFactory,
    PermitFactory,
    StatusHistoryFactory,
    UserFactory,
    VisitFactory,
)

pytestmark = pytest.mark.django_db

REGISTERED = sorted(
    (m._meta.app_label, m._meta.model_name) for m in django_admin.site._registry if m._meta.app_label in ("accounts", "applications")
)


def _instances(application):
    return {
        ("accounts", "user"): application.homeowner,
        ("applications", "property"): application.property,
        ("applications", "suite"): application.suite,
        ("applications", "application"): application,
        ("applications", "applicationstatushistory"): StatusHistoryFactory(application=application),
        ("applications", "complianceitem"): ComplianceItemFactory(application=application),
        ("applications", "permit"): PermitFactory(application=application),
        ("applications", "document"): DocumentFactory(application=application),
        ("applications", "visit"): VisitFactory(application=application),
    }


@pytest.fixture
def superadmin(db):
    """What `createsuperuser` produces: admin role + is_superuser. Model permissions in
    Django admin come from Django's permission system, not from `role` (see DECISIONS M6-2)."""
    from accounts.models import User

    return User.objects.create_superuser("root@example.com", "Sm0ke-Test-Passw0rd!", first_name="Root", last_name="Admin")


def test_all_nine_models_registered():
    assert len(REGISTERED) == 9


def test_any_admin_role_account_has_full_admin_access(client, admin):
    """An admin-role account created any way (factory, admin UI, API) gets full Django admin,
    not only accounts made with createsuperuser (DECISIONS M6-3, resolved)."""
    assert admin.is_superuser and admin.is_staff
    client.force_login(admin)
    assert client.get(reverse("admin:index")).status_code == 200
    assert client.get(reverse("admin:applications_application_changelist")).status_code == 200


@pytest.mark.parametrize("app_label,model", REGISTERED, ids=[f"{a}.{m}" for a, m in REGISTERED])
def test_changelist_add_and_change_render(client, superadmin, app_label, model):
    client.force_login(superadmin)
    application = ApplicationFactory()
    obj = _instances(application)[(app_label, model)]

    assert client.get(reverse(f"admin:{app_label}_{model}_changelist")).status_code == 200
    assert client.get(reverse(f"admin:{app_label}_{model}_change", args=[obj.pk])).status_code == 200
    add = client.get(reverse(f"admin:{app_label}_{model}_add"))
    # History is append-only: add is disabled there (403), everything else renders.
    assert add.status_code == (403 if model == "applicationstatushistory" else 200)


def test_application_change_page_shows_inlines(client, superadmin):
    client.force_login(superadmin)
    app = ApplicationFactory()
    StatusHistoryFactory(application=app, note="seed note")
    PermitFactory(application=app)
    html = client.get(reverse("admin:applications_application_change", args=[app.pk])).content.decode()
    for inline in ("status_history", "compliance_items", "permits", "documents", "visits"):
        assert f'id="{inline}-group"' in html, inline
    assert "seed note" in html


def test_history_change_form_is_read_only(client, superadmin):
    client.force_login(superadmin)
    row = StatusHistoryFactory()
    html = client.get(reverse("admin:applications_applicationstatushistory_change", args=[row.pk])).content.decode()
    assert 'name="note"' not in html  # rendered as text, not an input
    assert "Save" not in html or 'name="_save"' not in html


@pytest.mark.parametrize("role", ["homeowner", "staff"])
def test_non_admin_roles_cannot_open_admin(client, role):
    user = UserFactory(role=role)
    client.force_login(user)
    res = client.get(reverse("admin:index"))
    assert res.status_code == 302 and "/admin/login/" in res["Location"]


def test_autocomplete_endpoints_work(client, superadmin):
    """autocomplete_fields need search_fields on the target admin; a misconfiguration 500s here."""
    client.force_login(superadmin)
    UserFactory(email="findme@example.com", first_name="Find", last_name="Me")
    res = client.get(
        reverse("admin:autocomplete"),
        {"app_label": "applications", "model_name": "application", "field_name": "homeowner", "term": "findme"},
    )
    assert res.status_code == 200
    assert any("findme@example.com" in r["text"] for r in res.json()["results"])
