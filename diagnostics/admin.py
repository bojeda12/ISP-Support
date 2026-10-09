from django.contrib import admin
from .models import DiagnosticRun


@admin.register(DiagnosticRun)
class DiagnosticRunAdmin(admin.ModelAdmin):
    list_display = ("id", "internet_service", "scenario", "result", "source", "created_at")
    search_fields = ("scenario", "internet_service__service_identifier")
    list_filter = ("source", "result", "scenario", "created_at")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("internet_service",)
