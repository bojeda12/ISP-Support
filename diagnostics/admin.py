from django.contrib import admin
from .models import DiagnosticRun


@admin.register(DiagnosticRun)
class DiagnosticRunAdmin(admin.ModelAdmin):
    list_display = ("id", "internet_service", "scenario", "result", "result_code", "source", "created_at")
    search_fields = ("scenario", "internet_service__service_identifier")
    list_filter = ("source", "result", "result_code", "scenario", "created_at")
    readonly_fields = ("internet_service", "conversation", "scenario", "result", "result_code",
                       "metrics", "assessment", "source", "created_at", "updated_at", "started_at", "completed_at")
    list_select_related = ("internet_service",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
