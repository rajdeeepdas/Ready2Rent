import pytest
from django.contrib.auth import get_user_model

from accounts.models import UserRole

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_custom_user_model_is_active():
    assert User._meta.label == "accounts.User"
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username") or User._meta.get_field("email")


def test_username_field_removed():
    names = {f.name for f in User._meta.get_fields()}
    assert "username" not in names
    assert {"email", "role", "phone", "first_name", "last_name", "is_active", "date_joined"} <= names


def test_create_user_defaults():
    u = User.objects.create_user("Home.Owner@Example.com", "pw-12345", first_name="A", last_name="B")
    assert u.email == "home.owner@example.com"  # normalized + lowercased
    assert u.role == UserRole.HOMEOWNER
    assert u.is_active and not u.is_staff and not u.is_superuser
    assert u.check_password("pw-12345")


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user("", "pw")


def test_create_superuser_is_admin_role():
    u = User.objects.create_superuser("root@example.com", "pw-12345")
    assert u.role == UserRole.ADMIN and u.is_staff and u.is_superuser


def test_role_helpers(homeowner, staff, admin):
    assert homeowner.is_homeowner and not homeowner.is_ops and not homeowner.is_admin_role
    assert staff.is_ops and not staff.is_homeowner and not staff.is_admin_role
    assert admin.is_ops and admin.is_admin_role and not admin.is_homeowner


def test_uuid_primary_key(homeowner):
    import uuid

    assert isinstance(homeowner.pk, uuid.UUID)
