"""
Custom user model. docs/schema.md "User".

Email is the login field; there is no username column. Roles are a plain enum
column rather than Django groups because the product has exactly three fixed
roles and access rules are enforced in code at the queryset level.
"""

import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserRole(models.TextChoices):
    HOMEOWNER = "homeowner", "Homeowner"
    STAFF = "staff", "Staff"
    ADMIN = "admin", "Admin"


class UserManager(BaseUserManager):
    """Manager for an email-login user (no username)."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", UserRole.HOMEOWNER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    # Remove the username column entirely; email is the identifier.
    username = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("email address", unique=True)
    role = models.CharField(
        max_length=16, choices=UserRole.choices, default=UserRole.HOMEOWNER, db_index=True
    )
    # first_name, last_name, is_active, date_joined are inherited from AbstractUser.
    phone = models.CharField(max_length=32, null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]  # for createsuperuser prompts only

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        ordering = ["email"]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # Django admin access is derived from the application role, never set independently:
        # admin-role accounts get full Django admin (staff + superuser); every other role gets none.
        is_admin = self.role == UserRole.ADMIN
        self.is_staff = is_admin
        self.is_superuser = is_admin
        if "update_fields" in kwargs and kwargs["update_fields"] is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"is_staff", "is_superuser"}
        super().save(*args, **kwargs)

    # --- Role helpers used by permissions and queryset filtering -------------
    @property
    def is_homeowner(self) -> bool:
        return self.role == UserRole.HOMEOWNER

    @property
    def is_ops(self) -> bool:
        """Staff or admin: anyone who may see the ops queue."""
        return self.role in (UserRole.STAFF, UserRole.ADMIN)

    @property
    def is_admin_role(self) -> bool:
        return self.role == UserRole.ADMIN
