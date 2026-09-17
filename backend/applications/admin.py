from django.contrib import admin

from .models import (
    Application,
    ApplicationStatusHistory,
    ComplianceItem,
    Document,
    Permit,
    Property,
    Suite,
    Visit,
)


class SuiteInline(admin.TabularInline):
    model = Suite
    extra = 0
    fields = ["suite_type", "has_separate_entrance", "description"]


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["street_address", "city", "postal_code", "owner", "year_built", "land_use_district"]
    list_filter = ["city", "land_use_district"]
    search_fields = ["street_address", "postal_code", "owner__email"]
    autocomplete_fields = ["owner"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [SuiteInline]


@admin.register(Suite)
class SuiteAdmin(admin.ModelAdmin):
    list_display = ["__str__", "suite_type", "has_separate_entrance", "created_at"]
    list_filter = ["suite_type"]
    search_fields = ["property__street_address"]
    autocomplete_fields = ["property"]
    readonly_fields = ["id", "created_at", "updated_at"]


# ---- Application inlines ---------------------------------------------------
class StatusHistoryInline(admin.TabularInline):
    """Read-only in admin: history is append-only and written by the service layer."""

    model = ApplicationStatusHistory
    extra = 0
    can_delete = False
    fields = ["created_at", "from_status", "to_status", "changed_by", "note"]
    readonly_fields = fields
    ordering = ["created_at"]

    def has_add_permission(self, request, obj=None):
        return False


class ComplianceItemInline(admin.TabularInline):
    model = ComplianceItem
    extra = 0
    fields = ["item_type", "status", "notes"]


class PermitInline(admin.TabularInline):
    model = Permit
    extra = 0
    fields = ["permit_type", "status", "permit_number", "applied_date", "approved_date", "notes"]


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0
    fields = ["doc_type", "status", "file", "uploaded_by", "uploaded_at", "notes"]
    readonly_fields = ["uploaded_at"]
    autocomplete_fields = ["uploaded_by"]


class VisitInline(admin.TabularInline):
    model = Visit
    extra = 0
    fields = ["visit_type", "scheduled_for", "assigned_staff", "status", "outcome_notes"]
    autocomplete_fields = ["assigned_staff"]


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "homeowner", "property", "status", "assigned_staff", "submitted_at", "created_at"]
    list_filter = ["status", "pursuing_incentive", "assigned_staff"]
    search_fields = ["id", "homeowner__email", "property__street_address"]
    autocomplete_fields = ["homeowner", "property", "suite", "assigned_staff"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"
    inlines = [StatusHistoryInline, ComplianceItemInline, PermitInline, DocumentInline, VisitInline]


@admin.register(ApplicationStatusHistory)
class ApplicationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["application", "from_status", "to_status", "changed_by", "created_at"]
    list_filter = ["to_status"]
    readonly_fields = ["id", "application", "from_status", "to_status", "changed_by", "note", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ComplianceItem)
class ComplianceItemAdmin(admin.ModelAdmin):
    list_display = ["application", "item_type", "status", "updated_at"]
    list_filter = ["item_type", "status"]
    autocomplete_fields = ["application"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Permit)
class PermitAdmin(admin.ModelAdmin):
    list_display = ["application", "permit_type", "status", "permit_number", "applied_date", "approved_date"]
    list_filter = ["permit_type", "status"]
    autocomplete_fields = ["application"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["application", "doc_type", "status", "uploaded_by", "uploaded_at"]
    list_filter = ["doc_type", "status"]
    autocomplete_fields = ["application", "uploaded_by"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ["application", "visit_type", "scheduled_for", "assigned_staff", "status"]
    list_filter = ["visit_type", "status"]
    autocomplete_fields = ["application", "assigned_staff"]
    readonly_fields = ["id", "created_at", "updated_at"]
