"""
Homeowner surface: /api/homeowner/...

Ownership is enforced twice:
  1. Queryset level: every queryset is filtered to homeowner=request.user, so another
     homeowner's application is a 404 (indistinguishable from "does not exist").
  2. Object level: IsApplicationOwner re-checks the loaded object before any action.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F, Prefetch
from django.http import FileResponse
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsApplicationOwner, IsHomeowner
from core.throttles import ScopedWriteThrottle

from . import services
from .models import Application, ApplicationStatusHistory, Document
from .serializers import (
    INTAKE_OPTIONS,
    ApplicationDetailSerializer,
    ApplicationListSerializer,
    DocumentSerializer,
    IntakeSerializer,
    OtherDocumentSerializer,
    UploadSerializer,
    WithdrawSerializer,
)
from .state_machine import InvalidTransition


class HomeownerScopedMixin:
    """Base queryset for everything under /api/homeowner/: only the caller's rows."""

    permission_classes = [IsAuthenticated, IsHomeowner, IsApplicationOwner]

    def get_application_queryset(self):
        return (
            Application.objects.filter(homeowner=self.request.user)
            .select_related("property", "suite")
            .prefetch_related(
                "compliance_items",
                "documents",
                "permits",
                "visits",
                # Homeowners see status changes only. Internal ops notes are rows where
                # from_status == to_status and are excluded here.
                Prefetch(
                    "status_history",
                    queryset=ApplicationStatusHistory.objects.select_related("changed_by")
                    .exclude(from_status=F("to_status"))
                    .order_by("created_at"),
                ),
            )
        )

    def get_queryset(self):
        return self.get_application_queryset()


class HomeownerPingView(APIView):
    permission_classes = [IsAuthenticated, IsHomeowner]

    def get(self, request):
        return Response({"surface": "homeowner", "email": request.user.email})


class IntakeOptionsView(APIView):
    permission_classes = [IsAuthenticated, IsHomeowner]

    def get(self, request):
        return Response(INTAKE_OPTIONS)


class ApplicationListCreateView(HomeownerScopedMixin, GenericAPIView):
    serializer_class = ApplicationListSerializer
    # Creation only (GET is not counted): each intake emails every staff member.
    throttle_classes = [ScopedWriteThrottle]
    throttle_scope = "intake"

    def get(self, request):
        qs = self.get_queryset().order_by("-created_at")
        return Response(ApplicationListSerializer(qs, many=True).data)

    def post(self, request):
        """Intake submit: one atomic operation (docs/schema.md transaction boundary 1)."""
        serializer = IntakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        goals = d.get("goals") or {}
        try:
            application = services.submit_intake(
                homeowner=request.user,
                property_data=d["property"],
                suite_data=d["suite"],
                compliance=dict(d.get("compliance") or {}),
                other_issues=d.get("other_issues", ""),
                pursuing_incentive=goals.get("pursuing_incentive", False),
                wants_financing_guidance=goals.get("wants_financing_guidance", False),
                goals=goals.get("notes", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                getattr(exc, "message_dict", {"detail": exc.messages}), status=status.HTTP_400_BAD_REQUEST
            )
        application = self.get_queryset().get(pk=application.pk)
        return Response(ApplicationDetailSerializer(application).data, status=status.HTTP_201_CREATED)


class ApplicationDetailView(HomeownerScopedMixin, GenericAPIView):
    serializer_class = ApplicationDetailSerializer

    def get(self, request, pk):
        application = self.get_object()
        return Response(ApplicationDetailSerializer(application).data)


class ApplicationWithdrawView(HomeownerScopedMixin, GenericAPIView):
    serializer_class = WithdrawSerializer

    def post(self, request, pk):
        application = self.get_object()  # ownership checked here
        serializer = WithdrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.withdraw_application(
                application_id=application.pk, by_user=request.user, note=serializer.validated_data["note"]
            )
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        application = self.get_queryset().get(pk=pk)
        return Response(ApplicationDetailSerializer(application).data)


class DocumentCreateView(HomeownerScopedMixin, GenericAPIView):
    """POST multipart: add an extra 'other' document with its file."""

    serializer_class = OtherDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedWriteThrottle]
    throttle_scope = "uploads"

    def post(self, request, pk):
        application = self.get_object()
        serializer = OtherDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            document = services.add_other_document(
                application=application,
                uploaded_file=serializer.validated_data["file"],
                by_user=request.user,
                notes=serializer.validated_data["notes"],
            )
        except DjangoValidationError as exc:
            return Response(
                getattr(exc, "message_dict", {"detail": exc.messages}), status=status.HTTP_400_BAD_REQUEST
            )
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)


class DocumentScopedMixin(HomeownerScopedMixin):
    """Documents are reached only through an application the caller owns."""

    lookup_url_kwarg = "doc_pk"

    def get_queryset(self):
        return Document.objects.filter(
            application__homeowner=self.request.user, application_id=self.kwargs["pk"]
        ).select_related("application")


class DocumentUploadView(DocumentScopedMixin, GenericAPIView):
    serializer_class = UploadSerializer
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedWriteThrottle]
    throttle_scope = "uploads"

    def post(self, request, pk, doc_pk):
        document = self.get_object()
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.upload_document(
                document=document, uploaded_file=serializer.validated_data["file"], by_user=request.user
            )
        except services.DocumentLocked as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(DocumentSerializer(document).data)


class DocumentDownloadView(DocumentScopedMixin, GenericAPIView):
    """Authenticated download. Media is never served publicly (see config/urls.py)."""

    def get(self, request, pk, doc_pk):
        document = self.get_object()
        if not document.file:
            return Response({"detail": "No file uploaded yet."}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(document.file.open("rb"), as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1])
        return response
