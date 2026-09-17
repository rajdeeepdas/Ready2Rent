"""
Role permissions. Every API view declares one of these explicitly; the DRF default
(IsAuthenticated) is only a safety net.

Role vs Django flags:
  - `role` is the application role (homeowner / staff / admin) used by all API rules.
  - `is_staff` (Django admin-site access) is derived from role == admin on save.
    See accounts.models.User.save().
"""

from rest_framework.permissions import BasePermission

from .models import UserRole


class IsHomeowner(BasePermission):
    message = "This endpoint is for homeowners."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.role == UserRole.HOMEOWNER)


class IsOps(BasePermission):
    """Staff or admin: anyone allowed to see the ops queue."""

    message = "This endpoint is for staff."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.role in (UserRole.STAFF, UserRole.ADMIN))


class IsAdminRole(BasePermission):
    message = "This action requires an admin."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.role == UserRole.ADMIN)


class IsApplicationOwner(BasePermission):
    """
    Object-level ownership for the homeowner surface. Querysets are already filtered
    by homeowner; this is the second, independent check on the loaded object.
    Works for an Application or for any child row with an `application` FK.
    """

    message = "You do not have access to this application."

    def has_object_permission(self, request, view, obj):
        homeowner_id = getattr(obj, "homeowner_id", None)
        if homeowner_id is None:
            application = getattr(obj, "application", None)
            homeowner_id = getattr(application, "homeowner_id", None)
        return homeowner_id is not None and homeowner_id == request.user.id


class CanActOnApplication(BasePermission):
    """
    Object-level write rule for ops (docs/schema.md "Access control"):
      - admin: may act on any application
      - staff: may act only on applications assigned to them
    Read access for ops is handled by IsOps + queryset; this class only gates writes.
    Claiming an unassigned application is a dedicated transactional action (Milestone 4),
    not a generic PATCH of assigned_staff.
    """

    message = "You may only act on applications assigned to you."

    def has_object_permission(self, request, view, obj):
        u = request.user
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        if u.role == UserRole.ADMIN:
            return True
        if u.role == UserRole.STAFF:
            application = getattr(obj, "application", obj)
            return application.assigned_staff_id == u.id
        return False
