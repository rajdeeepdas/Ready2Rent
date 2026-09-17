from django.urls import path

from .views_ops import (
    ApplicationDetailView,
    AssignView,
    ClaimView,
    ComplianceItemCreateView,
    ComplianceItemEditView,
    DocumentReviewView,
    NoteView,
    OpsDocumentDownloadView,
    OpsOptionsView,
    OpsPingView,
    PermitCreateView,
    PermitEditView,
    QueueSummaryView,
    QueueView,
    StaffListView,
    TransitionView,
    VisitCreateView,
    VisitEditView,
)

app = "applications/<uuid:pk>/"

urlpatterns = [
    path("ping/", OpsPingView.as_view(), name="ops-ping"),
    path("options/", OpsOptionsView.as_view(), name="ops-options"),
    path("staff/", StaffListView.as_view(), name="ops-staff"),
    path("applications/", QueueView.as_view(), name="ops-queue"),
    path("applications/summary/", QueueSummaryView.as_view(), name="ops-queue-summary"),
    path(app, ApplicationDetailView.as_view(), name="ops-application"),
    path(app + "transition/", TransitionView.as_view(), name="ops-transition"),
    path(app + "claim/", ClaimView.as_view(), name="ops-claim"),
    path(app + "assign/", AssignView.as_view(), name="ops-assign"),
    path(app + "notes/", NoteView.as_view(), name="ops-notes"),
    path(app + "compliance/", ComplianceItemCreateView.as_view(), name="ops-compliance-create"),
    path(app + "compliance/<uuid:child_pk>/", ComplianceItemEditView.as_view(), name="ops-compliance-edit"),
    path(app + "permits/", PermitCreateView.as_view(), name="ops-permit-create"),
    path(app + "permits/<uuid:child_pk>/", PermitEditView.as_view(), name="ops-permit-edit"),
    path(app + "visits/", VisitCreateView.as_view(), name="ops-visit-create"),
    path(app + "visits/<uuid:child_pk>/", VisitEditView.as_view(), name="ops-visit-edit"),
    path(app + "documents/review/", DocumentReviewView.as_view(), name="ops-document-review"),
    path(app + "documents/<uuid:doc_pk>/download/", OpsDocumentDownloadView.as_view(), name="ops-document-download"),
]
