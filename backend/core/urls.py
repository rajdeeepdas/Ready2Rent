from django.urls import path

from .views import HealthView, LivenessView

urlpatterns = [
    path("livez/", LivenessView.as_view(), name="livez"),
    path("health/", HealthView.as_view(), name="health"),
]
