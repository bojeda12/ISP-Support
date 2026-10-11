from django.contrib import admin
from .models import Customer, InternetService


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "external_id", "email", "phone", "created_at")
    search_fields = ("name", "external_id", "email", "phone")
    list_filter = ("created_at",)
    readonly_fields = ("id", "created_at", "updated_at")

    def get_readonly_fields(self,request,obj=None):
        return self.readonly_fields + (() if request.user.is_superuser else ('organization',))


@admin.register(InternetService)
class InternetServiceAdmin(admin.ModelAdmin):
    list_display = ("service_identifier", "customer", "plan_name", "status", "connectivity_status")
    search_fields = ("service_identifier", "customer__name", "customer__external_id", "cpe_identifier")
    list_filter = ("status", "connectivity_status", "plan_name")
    list_select_related = ("customer",)
    autocomplete_fields = ("customer",)

    def get_readonly_fields(self, request, obj=None):
        return ("customer",) if obj else ()
