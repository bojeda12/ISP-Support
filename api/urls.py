from django.urls import path

from .views import health
from diagnostics.api import RunDiagnosticView

app_name = "api"
urlpatterns = [
    path("health/", health, name="health"),
    path("diagnostics/run/", RunDiagnosticView.as_view(), name="diagnostic-run"),
]
