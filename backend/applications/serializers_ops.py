"""Ops-surface serializers. Unlike the homeowner ones these expose staff identities and
homeowner contact details, because the reader is staff."""

from django.urls import reverse
from rest_framework import serializers

from accounts.models import User, UserRole

from .enums import (
    ApplicationStatus,
    ComplianceItemType,
    ComplianceStatus,
    DocumentStatus,
    PermitStatus,
    PermitType,
    VisitStatus,
    VisitType,
)
from .models import Application, ApplicationStatusHistory, ComplianceItem, Document, Permit, Visit
from .serializers import PermitSerializer, PropertySerializer, SuiteSerializer
from .services import allowed_transitions, completion_blockers


class StaffUserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "role"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class HomeownerContactSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "phone"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class OpsHistorySerializer(serializers.ModelSerializer):
    changed_by = StaffUserSerializer(read_only=True)
    is_note = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = ["id", "from_status", "to_status", "note", "created_at", "changed_by", "is_note"]

    def get_is_note(self, obj):
        return obj.from_status == obj.to_status


class OpsComplianceItemSerializer(serializers.ModelSerializer):
    item_type_display = serializers.CharField(source="get_item_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ComplianceItem
        fields = ["id", "item_type", "item_type_display", "status", "status_display", "notes", "updated_at"]
        read_only_fields = ["id", "item_type", "updated_at"]


class OpsDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    file_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "doc_type", "doc_type_display", "status", "status_display", "file_name",
            "download_url", "uploaded_at", "notes", "updated_at",
        ]

    def get_file_name(self, obj):
        return obj.file.name.rsplit("/", 1)[-1] if obj.file else None

    def get_download_url(self, obj):
        if not obj.file:
            return None
        return reverse("ops-document-download", kwargs={"pk": obj.application_id, "doc_pk": obj.pk})


class OpsVisitSerializer(serializers.ModelSerializer):
    visit_type_display = serializers.CharField(source="get_visit_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    assigned_staff = StaffUserSerializer(read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id", "visit_type", "visit_type_display", "scheduled_for", "assigned_staff",
            "status", "status_display", "outcome_notes", "created_at", "updated_at",
        ]


# ---------------------------------------------------------------------------
# Queue list + detail
# ---------------------------------------------------------------------------


class QueueItemSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    homeowner = HomeownerContactSerializer(read_only=True)
    assigned_staff = StaffUserSerializer(read_only=True)
    street_address = serializers.CharField(source="property.street_address", read_only=True)
    postal_code = serializers.CharField(source="property.postal_code", read_only=True)
    suite_type = serializers.CharField(source="suite.suite_type", read_only=True)
    # Annotated in the view
    docs_pending_review = serializers.IntegerField(read_only=True)
    docs_required = serializers.IntegerField(read_only=True)
    docs_uploaded = serializers.IntegerField(read_only=True)
    items_needing_work = serializers.IntegerField(read_only=True)

    class Meta:
        model = Application
        fields = [
            "id", "status", "status_display", "homeowner", "assigned_staff", "street_address", "postal_code",
            "suite_type", "pursuing_incentive", "submitted_at", "updated_at",
            "docs_pending_review", "docs_required", "docs_uploaded", "items_needing_work",
        ]


class OpsApplicationDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    homeowner = HomeownerContactSerializer(read_only=True)
    assigned_staff = StaffUserSerializer(read_only=True)
    property = PropertySerializer(read_only=True)
    suite = SuiteSerializer(read_only=True)
    compliance_items = OpsComplianceItemSerializer(many=True, read_only=True)
    documents = OpsDocumentSerializer(many=True, read_only=True)
    permits = PermitSerializer(many=True, read_only=True)
    visits = OpsVisitSerializer(many=True, read_only=True)
    status_history = OpsHistorySerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    completion_blockers = serializers.SerializerMethodField()
    can_act = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id", "status", "status_display", "homeowner", "assigned_staff", "pursuing_incentive",
            "estimated_cost", "submitted_at", "created_at", "updated_at",
            "allowed_transitions", "completion_blockers", "can_act",
            "property", "suite", "compliance_items", "documents", "permits", "visits", "status_history",
        ]

    def get_allowed_transitions(self, obj):
        return allowed_transitions(obj)

    def get_completion_blockers(self, obj):
        return completion_blockers(obj)

    def get_can_act(self, obj):
        user = self.context["request"].user
        return user.role == UserRole.ADMIN or obj.assigned_staff_id == user.id


# ---------------------------------------------------------------------------
# Write serializers
# ---------------------------------------------------------------------------


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class AssignSerializer(serializers.Serializer):
    staff_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=4000)


class ApplicationEditSerializer(serializers.Serializer):
    """Ops-editable scalar fields. land_use_district lives on the property (eligibility check)."""

    estimated_cost = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0)
    pursuing_incentive = serializers.BooleanField(required=False)
    land_use_district = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=50)


class ComplianceItemEditSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ComplianceStatus.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class ComplianceItemCreateSerializer(serializers.Serializer):
    """Only 'other' items can be added; the standard set is seeded at intake."""

    status = serializers.ChoiceField(choices=ComplianceStatus.choices, default=ComplianceStatus.NEEDS_WORK)
    notes = serializers.CharField(max_length=4000)

    def create(self, validated):
        return ComplianceItem.objects.create(item_type=ComplianceItemType.OTHER, **validated)


class PermitWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permit
        fields = ["permit_type", "permit_number", "status", "applied_date", "approved_date", "notes"]
        extra_kwargs = {"permit_type": {"required": True}}

    def validate(self, attrs):
        applied = attrs.get("applied_date", getattr(self.instance, "applied_date", None))
        approved = attrs.get("approved_date", getattr(self.instance, "approved_date", None))
        if applied and approved and approved < applied:
            raise serializers.ValidationError({"approved_date": "Cannot be before the applied date."})
        return attrs


class VisitWriteSerializer(serializers.Serializer):
    visit_type = serializers.ChoiceField(choices=VisitType.choices, required=False)
    scheduled_for = serializers.DateTimeField(required=False)
    assigned_staff_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=VisitStatus.choices, required=False)
    outcome_notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class DocumentDecisionSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=[(DocumentStatus.ACCEPTED, "accepted"), (DocumentStatus.REJECTED, "rejected")])
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class DocumentReviewSerializer(serializers.Serializer):
    decisions = DocumentDecisionSerializer(many=True)


OPS_OPTIONS = {
    "statuses": [{"value": v, "label": l} for v, l in ApplicationStatus.choices],
    "compliance_statuses": [{"value": v, "label": l} for v, l in ComplianceStatus.choices],
    "permit_types": [{"value": v, "label": l} for v, l in PermitType.choices],
    "permit_statuses": [{"value": v, "label": l} for v, l in PermitStatus.choices],
    "visit_types": [{"value": v, "label": l} for v, l in VisitType.choices],
    "visit_statuses": [{"value": v, "label": l} for v, l in VisitStatus.choices],
}
