"""
Ops surface: /api/ops/...

Access (docs/schema.md "Access control"):
  - IsOps (staff or admin) on every view: staff read everything.
  - CanActOnApplication on every write: admin acts on any application; staff only on
    applications assigned to them. Claiming an unassigned application is the one
    exception and is a dedicated, row-locked action.
  - Assign / reassign to another person is admin-only.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, UserRole
from accounts.permissions import CanActOnApplication, IsAdminRole, IsOps

from . import services
from .cache import get_cached, queue_cache_key, set_cached
from .enums import ApplicationStatus, ComplianceItemType, DocumentStatus, SuiteType
from .models import Application, ApplicationStatusHistory, ComplianceItem, Document, Permit, Visit
from .serializers_ops import (
    OPS_OPTIONS,
    ApplicationEditSerializer,
    AssignSerializer,
    ComplianceItemCreateSerializer,
    ComplianceItemEditSerializer,
    DocumentReviewSerializer,
    NoteSerializer,
    OpsApplicationDetailSerializer,
    OpsComplianceItemSerializer,
    OpsDocumentSerializer,
    OpsVisitSerializer,
    PermitSerializer,
    PermitWriteSerializer,
    QueueItemSerializer,
    StaffUserSerializer,
    TransitionSerializer,
    VisitWriteSerializer,
)
from .state_machine import InvalidTransition

OPEN_STATUSES = [s for s in ApplicationStatus.values if s not in (ApplicationStatus.COMPLETE, ApplicationStatus.WITHDRAWN)]


def _django_errors(exc: DjangoValidationError):
    return getattr(exc, "message_dict", None) or {"detail": exc.messages}


class OpsBase:
    permission_classes = [IsAuthenticated, IsOps, CanActOnApplication]

    def get_queryset(self):
        return (
            Application.objects.select_related("homeowner", "assigned_staff", "property", "suite")
            .prefetch_related(
                "compliance_items",
                "documents",
                "permits",
                Prefetch("visits", queryset=Visit.objects.select_related("assigned_staff")),
                Prefetch(
                    "status_history",
                    queryset=ApplicationStatusHistory.objects.select_related("changed_by").order_by("created_at"),
                ),
            )
        )

    def detail(self, pk):
        application = self.get_queryset().get(pk=pk)
        return Response(OpsApplicationDetailSerializer(application, context={"request": self.request}).data)


class OpsPingView(APIView):
    permission_classes = [IsAuthenticated, IsOps]

    def get(self, request):
        return Response({"surface": "ops", "email": request.user.email, "role": request.user.role})


class OpsOptionsView(APIView):
    permission_classes = [IsAuthenticated, IsOps]

    def get(self, request):
        return Response(OPS_OPTIONS)


class StaffListView(APIView):
    """Ops users, for assignment pickers and visit scheduling."""

    permission_classes = [IsAuthenticated, IsOps]

    def get(self, request):
        qs = User.objects.filter(role__in=[UserRole.STAFF, UserRole.ADMIN], is_active=True).order_by("first_name", "email")
        return Response(StaffUserSerializer(qs, many=True).data)


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class QueueView(OpsBase, GenericAPIView):
    """
    GET /api/ops/applications/?status=&assigned=me|unassigned|<uuid>&suite_type=&q=&ordering=&page=
    Default: open applications, newest first. Paginated (PAGE_SIZE).
    """

    serializer_class = QueueItemSerializer

    def get_queryset(self):
        qs = (
            Application.objects.select_related("homeowner", "assigned_staff", "property", "suite")
            .annotate(
                docs_pending_review=Count("documents", filter=Q(documents__status=DocumentStatus.UPLOADED), distinct=True),
                docs_required=Count("documents", filter=~Q(documents__doc_type="other"), distinct=True),
                docs_uploaded=Count(
                    "documents",
                    filter=~Q(documents__doc_type="other") & ~Q(documents__status=DocumentStatus.REQUIRED),
                    distinct=True,
                ),
                items_needing_work=Count("compliance_items", filter=Q(compliance_items__status="needs_work"), distinct=True),
            )
        )
        p = self.request.query_params
        status_param = p.get("status")
        if status_param == "all":
            pass
        elif status_param:
            qs = qs.filter(status__in=[s for s in status_param.split(",") if s in ApplicationStatus.values])
        else:
            qs = qs.filter(status__in=OPEN_STATUSES)

        assigned = p.get("assigned")
        if assigned == "me":
            qs = qs.filter(assigned_staff=self.request.user)
        elif assigned == "unassigned":
            qs = qs.filter(assigned_staff__isnull=True)
        elif assigned:
            try:
                qs = qs.filter(assigned_staff_id=uuid.UUID(assigned))
            except ValueError:
                raise DRFValidationError({"assigned": "Use 'me', 'unassigned', or a user id."})

        if p.get("suite_type") in SuiteType.values:
            qs = qs.filter(suite__suite_type=p["suite_type"])

        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(property__street_address__icontains=q)
                | Q(property__postal_code__icontains=q)
                | Q(homeowner__email__icontains=q)
                | Q(homeowner__first_name__icontains=q)
                | Q(homeowner__last_name__icontains=q)
            )

        ordering = p.get("ordering", "-created_at")
        allowed = {"created_at", "-created_at", "updated_at", "-updated_at", "submitted_at", "-submitted_at", "status", "-status"}
        qs = qs.order_by(ordering if ordering in allowed else "-created_at", "-created_at")
        return qs

    def _params(self):
        p = self.request.query_params
        return {k: p.get(k, "") for k in ("status", "assigned", "suite_type", "q", "ordering", "page")}

    def get(self, request):
        key = queue_cache_key("list", request.user, self._params())
        cached = get_cached(key)
        if cached is not None:
            return Response(cached, headers={"X-Cache": "HIT"})
        page = self.paginate_queryset(self.get_queryset())
        data = self.get_paginated_response(QueueItemSerializer(page, many=True).data).data
        set_cached(key, data)
        return Response(data, headers={"X-Cache": "MISS"})


class QueueSummaryView(APIView):
    """Counts per status plus the caller's own and unassigned open counts. Cached per user."""

    permission_classes = [IsAuthenticated, IsOps]

    def get(self, request):
        key = queue_cache_key("summary", request.user, {})
        cached = get_cached(key)
        if cached is not None:
            return Response(cached, headers={"X-Cache": "HIT"})
        by_status = {row["status"]: row["n"] for row in Application.objects.values("status").annotate(n=Count("id"))}
        open_qs = Application.objects.filter(status__in=OPEN_STATUSES)
        data = {
            "by_status": {s: by_status.get(s, 0) for s in ApplicationStatus.values},
            "open": open_qs.count(),
            "mine": open_qs.filter(assigned_staff=request.user).count(),
            "unassigned": open_qs.filter(assigned_staff__isnull=True).count(),
            "docs_pending_review": Document.objects.filter(
                application__status__in=OPEN_STATUSES, status=DocumentStatus.UPLOADED
            ).count(),
        }
        set_cached(key, data)
        return Response(data, headers={"X-Cache": "MISS"})


# ---------------------------------------------------------------------------
# Application detail + actions
# ---------------------------------------------------------------------------


class ApplicationDetailView(OpsBase, GenericAPIView):
    serializer_class = OpsApplicationDetailSerializer

    def get(self, request, pk):
        self.get_object()
        return self.detail(pk)

    def patch(self, request, pk):
        application = self.get_object()
        serializer = ApplicationEditSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        fields = []
        if "estimated_cost" in d:
            application.estimated_cost = d["estimated_cost"]
            fields.append("estimated_cost")
        if "pursuing_incentive" in d:
            application.pursuing_incentive = d["pursuing_incentive"]
            fields.append("pursuing_incentive")
        if fields:
            application.save(update_fields=fields + ["updated_at"])
        if "land_use_district" in d:
            application.property.land_use_district = d["land_use_district"] or None
            application.property.save(update_fields=["land_use_district", "updated_at"])
        return self.detail(pk)


class TransitionView(OpsBase, GenericAPIView):
    serializer_class = TransitionSerializer

    def post(self, request, pk):
        self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.transition_application(
                application_id=pk,
                to_status=serializer.validated_data["to_status"],
                by_user=request.user,
                note=serializer.validated_data["note"],
            )
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return self.detail(pk)


class ClaimView(OpsBase, GenericAPIView):
    """Staff self-claim of an UNASSIGNED application. Object permission is bypassed on
    purpose (an unassigned application has no owner yet); the service enforces the rule."""

    permission_classes = [IsAuthenticated, IsOps]
    serializer_class = NoteSerializer

    def post(self, request, pk):
        self.get_object()
        try:
            services.claim_application(application_id=pk, by_user=request.user)
        except services.AssignmentConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return self.detail(pk)


class AssignView(OpsBase, GenericAPIView):
    """Admin only: assign, reassign, or unassign (staff_id=null)."""

    permission_classes = [IsAuthenticated, IsOps, IsAdminRole]
    serializer_class = AssignSerializer

    def post(self, request, pk):
        self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff_id = serializer.validated_data["staff_id"]
        staff = None
        if staff_id:
            staff = User.objects.filter(pk=staff_id, is_active=True).first()
            if staff is None:
                return Response({"staff_id": ["Unknown user."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            services.assign_application(
                application_id=pk, staff=staff, by_user=request.user, note=serializer.validated_data["note"]
            )
        except DjangoValidationError as exc:
            return Response(_django_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return self.detail(pk)


class NoteView(OpsBase, GenericAPIView):
    serializer_class = NoteSerializer

    def post(self, request, pk):
        self.get_object()
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.add_note(application_id=pk, by_user=request.user, note=serializer.validated_data["note"])
        except DjangoValidationError as exc:
            return Response(_django_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return self.detail(pk)


# ---------------------------------------------------------------------------
# Children: compliance items, permits, visits, documents
# ---------------------------------------------------------------------------


class ChildBase(OpsBase):
    """Child rows are reached through their application; object permission resolves
    through obj.application (see CanActOnApplication)."""

    child_model = None
    lookup_url_kwarg = "child_pk"

    def get_queryset(self):
        return self.child_model.objects.filter(application_id=self.kwargs["pk"]).select_related("application")

    def get_application(self):
        # Runs the object permission against the parent application.
        application = Application.objects.get(pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, application)
        return application


class ComplianceItemCreateView(ChildBase, GenericAPIView):
    child_model = ComplianceItem
    serializer_class = ComplianceItemCreateSerializer

    def post(self, request, pk):
        application = self.get_application()
        serializer = ComplianceItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = ComplianceItem.objects.create(
            application=application, item_type=ComplianceItemType.OTHER, **serializer.validated_data
        )
        return Response(OpsComplianceItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ComplianceItemEditView(ChildBase, GenericAPIView):
    child_model = ComplianceItem
    serializer_class = ComplianceItemEditSerializer

    def patch(self, request, pk, child_pk):
        item = self.get_object()
        serializer = ComplianceItemEditSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for k, v in serializer.validated_data.items():
            setattr(item, k, v)
        item.save()
        return Response(OpsComplianceItemSerializer(item).data)


class PermitCreateView(ChildBase, GenericAPIView):
    child_model = Permit
    serializer_class = PermitWriteSerializer

    def post(self, request, pk):
        application = self.get_application()
        serializer = PermitWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if Permit.objects.filter(application=application, permit_type=serializer.validated_data["permit_type"]).exists():
            return Response({"permit_type": ["This permit already exists for the application."]}, status=status.HTTP_409_CONFLICT)
        permit = Permit.objects.create(application=application, **serializer.validated_data)
        return Response(PermitSerializer(permit).data, status=status.HTTP_201_CREATED)


class PermitEditView(ChildBase, GenericAPIView):
    child_model = Permit
    serializer_class = PermitWriteSerializer

    def patch(self, request, pk, child_pk):
        permit = self.get_object()
        serializer = PermitWriteSerializer(permit, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.validated_data.pop("permit_type", None)  # type is fixed once created
        for k, v in serializer.validated_data.items():
            setattr(permit, k, v)
        permit.save()
        return Response(PermitSerializer(permit).data)


def _apply_visit_fields(visit, data, request):
    if "assigned_staff_id" in data:
        sid = data["assigned_staff_id"]
        if sid is None:
            visit.assigned_staff = None
        else:
            staff = User.objects.filter(pk=sid, is_active=True).first()
            if staff is None:
                raise DjangoValidationError({"assigned_staff_id": "Unknown user."})
            visit.assigned_staff = staff  # role validated in Visit.save()
    for k in ("visit_type", "scheduled_for", "status", "outcome_notes"):
        if k in data:
            setattr(visit, k, data[k])


class VisitCreateView(ChildBase, GenericAPIView):
    child_model = Visit
    serializer_class = VisitWriteSerializer

    def post(self, request, pk):
        application = self.get_application()
        serializer = VisitWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        missing = [k for k in ("visit_type", "scheduled_for") if k not in d]
        if missing:
            return Response({k: ["This field is required."] for k in missing}, status=status.HTTP_400_BAD_REQUEST)
        visit = Visit(application=application, assigned_staff=request.user)
        try:
            _apply_visit_fields(visit, d, request)
            visit.save()
        except DjangoValidationError as exc:
            return Response(_django_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(OpsVisitSerializer(visit).data, status=status.HTTP_201_CREATED)


class VisitEditView(ChildBase, GenericAPIView):
    child_model = Visit
    serializer_class = VisitWriteSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("assigned_staff")

    def patch(self, request, pk, child_pk):
        visit = self.get_object()
        serializer = VisitWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            _apply_visit_fields(visit, serializer.validated_data, request)
            visit.save()
        except DjangoValidationError as exc:
            return Response(_django_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(OpsVisitSerializer(visit).data)


class DocumentReviewView(OpsBase, GenericAPIView):
    """Bulk accept / reject in one transaction (docs/schema.md boundary 5)."""

    serializer_class = DocumentReviewSerializer

    def post(self, request, pk):
        self.get_object()
        serializer = DocumentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            docs = services.review_documents(
                application_id=pk, decisions=serializer.validated_data["decisions"], by_user=request.user
            )
        except DjangoValidationError as exc:
            return Response(_django_errors(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(OpsDocumentSerializer(docs, many=True).data)


class OpsDocumentDownloadView(ChildBase, GenericAPIView):
    child_model = Document
    lookup_url_kwarg = "doc_pk"
    permission_classes = [IsAuthenticated, IsOps]  # reading is allowed for all ops users

    def get(self, request, pk, doc_pk):
        document = self.get_object()
        if not document.file:
            return Response({"detail": "No file uploaded yet."}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1])
