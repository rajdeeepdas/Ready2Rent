from django.urls import path

from .views_homeowner import (
    ApplicationDetailView,
    ApplicationListCreateView,
    ApplicationWithdrawView,
    DocumentCreateView,
    DocumentDownloadView,
    DocumentUploadView,
    HomeownerPingView,
    IntakeOptionsView,
)

urlpatterns = [
    path("ping/", HomeownerPingView.as_view(), name="homeowner-ping"),
    path("intake-options/", IntakeOptionsView.as_view(), name="homeowner-intake-options"),
    path("applications/", ApplicationListCreateView.as_view(), name="homeowner-applications"),
    path("applications/<uuid:pk>/", ApplicationDetailView.as_view(), name="homeowner-application"),
    path("applications/<uuid:pk>/withdraw/", ApplicationWithdrawView.as_view(), name="homeowner-application-withdraw"),
    path("applications/<uuid:pk>/documents/", DocumentCreateView.as_view(), name="homeowner-document-create"),
    path(
        "applications/<uuid:pk>/documents/<uuid:doc_pk>/upload/",
        DocumentUploadView.as_view(),
        name="homeowner-document-upload",
    ),
    path(
        "applications/<uuid:pk>/documents/<uuid:doc_pk>/download/",
        DocumentDownloadView.as_view(),
        name="homeowner-document-download",
    ),
]
