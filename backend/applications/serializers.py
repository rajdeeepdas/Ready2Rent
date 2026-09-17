from django.urls import reverse
from rest_framework import serializers

from accounts.models import UserRole

from .enums import ApplicationStatus, ComplianceItemType, ComplianceStatus, SuiteType
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
from .services import SELF_REPORTABLE_STATUSES, STANDARD_COMPLIANCE_ITEMS

# ---------------------------------------------------------------------------
# Read serializers (homeowner view of their own application)
# ---------------------------------------------------------------------------


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "street_address", "city", "province", "postal_code", "land_use_district", "year_built"]
        read_only_fields = fields


class SuiteSerializer(serializers.ModelSerializer):
    suite_type_display = serializers.CharField(source="get_suite_type_display", read_only=True)

    class Meta:
        model = Suite
        fields = ["id", "suite_type", "suite_type_display", "has_separate_entrance", "description"]
        read_only_fields = fields


class ComplianceItemSerializer(serializers.ModelSerializer):
    item_type_display = serializers.CharField(source="get_item_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ComplianceItem
        fields = ["id", "item_type", "item_type_display", "status", "status_display", "notes", "updated_at"]
        read_only_fields = fields


class PermitSerializer(serializers.ModelSerializer):
    permit_type_display = serializers.CharField(source="get_permit_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Permit
        fields = [
            "id", "permit_type", "permit_type_display", "permit_number", "status", "status_display",
            "applied_date", "approved_date", "notes",
        ]
        read_only_fields = fields


class VisitSerializer(serializers.ModelSerializer):
    visit_type_display = serializers.CharField(source="get_visit_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Visit
        fields = ["id", "visit_type", "visit_type_display", "scheduled_for", "status", "status_display", "outcome_notes"]
        read_only_fields = fields


class DocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    file_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "doc_type", "doc_type_display", "status", "status_display",
            "file_name", "download_url", "uploaded_at", "notes", "updated_at",
        ]
        read_only_fields = fields

    def get_file_name(self, obj):
        return obj.file.name.rsplit("/", 1)[-1] if obj.file else None

    def get_download_url(self, obj):
        if not obj.file:
            return None
        return reverse(
            "homeowner-document-download",
            kwargs={"pk": obj.application_id, "doc_pk": obj.pk},
        )


class StatusHistorySerializer(serializers.ModelSerializer):
    """Homeowner-facing: never exposes staff identities, only who-kind."""

    changed_by_role = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = ["id", "from_status", "to_status", "note", "created_at", "changed_by_role"]
        read_only_fields = fields

    def get_changed_by_role(self, obj):
        return "you" if obj.changed_by.role == UserRole.HOMEOWNER else "ready2rent"


class ApplicationListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    street_address = serializers.CharField(source="property.street_address", read_only=True)
    suite_type = serializers.CharField(source="suite.suite_type", read_only=True)
    documents_required = serializers.SerializerMethodField()
    documents_uploaded = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id", "status", "status_display", "street_address", "suite_type",
            "submitted_at", "updated_at", "documents_required", "documents_uploaded",
        ]

    def get_documents_required(self, obj):
        return sum(1 for d in obj.documents.all() if d.doc_type != "other")

    def get_documents_uploaded(self, obj):
        return sum(1 for d in obj.documents.all() if d.doc_type != "other" and d.file)


class ApplicationDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    property = PropertySerializer(read_only=True)
    suite = SuiteSerializer(read_only=True)
    compliance_items = ComplianceItemSerializer(many=True, read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)
    permits = PermitSerializer(many=True, read_only=True)
    visits = VisitSerializer(many=True, read_only=True)
    status_history = StatusHistorySerializer(many=True, read_only=True)
    can_withdraw = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id", "status", "status_display", "pursuing_incentive", "estimated_cost",
            "submitted_at", "created_at", "updated_at", "can_withdraw",
            "property", "suite", "compliance_items", "documents", "permits", "visits", "status_history",
        ]

    def get_can_withdraw(self, obj):
        from .state_machine import TRANSITIONS

        return ApplicationStatus.WITHDRAWN in TRANSITIONS.get(obj.status, ())


# ---------------------------------------------------------------------------
# Write serializers
# ---------------------------------------------------------------------------


class IntakePropertySerializer(serializers.Serializer):
    street_address = serializers.CharField(max_length=255)
    city = serializers.CharField(max_length=100, default="Calgary")
    province = serializers.CharField(max_length=2, default="AB")
    postal_code = serializers.CharField(max_length=10)
    year_built = serializers.IntegerField(required=False, allow_null=True, min_value=1800, max_value=2100)


class IntakeSuiteSerializer(serializers.Serializer):
    suite_type = serializers.ChoiceField(choices=SuiteType.choices)
    has_separate_entrance = serializers.BooleanField(required=False, allow_null=True, default=None)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)


class IntakeGoalsSerializer(serializers.Serializer):
    pursuing_incentive = serializers.BooleanField(default=False)
    wants_financing_guidance = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)


class IntakeSerializer(serializers.Serializer):
    """The whole multi-step intake, submitted once. Validation only; creation is
    services.submit_intake() inside one transaction."""

    property = IntakePropertySerializer()
    suite = IntakeSuiteSerializer()
    compliance = serializers.DictField(
        child=serializers.ChoiceField(choices=[(s, s) for s in SELF_REPORTABLE_STATUSES]),
        required=False,
        default=dict,
    )
    other_issues = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)
    goals = IntakeGoalsSerializer(required=False, default=dict)

    def validate_compliance(self, value):
        unknown = [k for k in value if k not in STANDARD_COMPLIANCE_ITEMS]
        if unknown:
            raise serializers.ValidationError(f"Unknown compliance items: {unknown}")
        return value


class OtherDocumentSerializer(serializers.Serializer):
    file = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class WithdrawSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


# Exposed to the SPA so the wizard renders the same choices the API validates.
INTAKE_OPTIONS = {
    "suite_types": [{"value": v, "label": l} for v, l in SuiteType.choices],
    "compliance_items": [
        {"value": v, "label": l} for v, l in ComplianceItemType.choices if v != ComplianceItemType.OTHER
    ],
    "self_report_statuses": [
        {"value": ComplianceStatus.COMPLIANT, "label": "Yes, already meets this"},
        {"value": ComplianceStatus.NEEDS_WORK, "label": "No, needs work"},
        {"value": ComplianceStatus.NOT_ASSESSED, "label": "Not sure"},
    ],
}
