from django.urls import path

from .views import health

app_name = "api"
urlpatterns = [path("health/", health, name="health")]
