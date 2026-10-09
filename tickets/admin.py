from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .models import Ticket, TicketEvent
from .services import change_ticket_status, create_ticket, update_ticket_details, validate_transition


class TicketAdminForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = "__all__"

    def clean_status(self):
        status = self.cleaned_data["status"]
        if self.instance.pk and not self.instance._state.adding:
            current = Ticket.objects.get(pk=self.instance.pk)
            if current.status != status:
                try:
                    validate_transition(current, status, self.actor)
                except PermissionDenied as error:
                    raise ValidationError(str(error)) from error
                except ValidationError as error:
                    raise ValidationError(error.messages) from error
        elif status != Ticket.Status.OPEN:
            raise ValidationError("New tickets must start OPEN.")
        return status


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    fields = ("created_at", "description", "from_status", "to_status", "user")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    form = TicketAdminForm
    list_display = ("number", "title", "customer", "internet_service", "priority", "status", "assigned_technician", "created_at")
    search_fields = ("number", "title", "incident_key", "customer__name", "customer__external_id", "internet_service__service_identifier")
    list_filter = ("status", "priority", "assigned_technician", "created_at")
    readonly_fields = ("id", "number", "created_at", "updated_at", "resolved_at", "support_context")
    list_select_related = ("customer", "internet_service", "assigned_technician")
    inlines = (TicketEventInline,)

    @admin.display(description="Conversation and diagnostics")
    def support_context(self, obj):
        if not obj or not obj.conversation_id:
            return "No associated conversation."
        runs = obj.conversation.diagnostic_runs.filter(internet_service_id=obj.internet_service_id).order_by("-created_at")
        links = format_html_join(" · ", '<a href="{}">{} — {} ({})</a>', (
            (reverse("admin:diagnostics_diagnosticrun_change", args=[run.pk]), run.result_code, run.get_result_display(), run.created_at)
            for run in runs
        ))
        return format_html('<a href="{}">View conversation #{}</a><p>{}</p>',
                           reverse("admin:conversations_conversation_change", args=[obj.conversation_id]),
                           obj.conversation_id, links or "No diagnostics.")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Clase específica de esta petición: no compartir usuarios entre peticiones.
        return type("ActorTicketForm", (form,), {"actor": request.user})

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("customer", "internet_service", "conversation", "incident_key") if obj else ())

    def save_model(self, request, obj, form, change):
        if not change:
            ticket = create_ticket(
                customer=obj.customer, internet_service=obj.internet_service,
                conversation=obj.conversation, incident_key=obj.incident_key,
                title=obj.title, description=obj.description, priority=obj.priority,
                assigned_technician=obj.assigned_technician, user=request.user,
            )
            obj.__dict__.update(ticket.__dict__)
            return
        target_status = obj.status
        current = update_ticket_details(
            ticket=obj, title=obj.title, description=obj.description, priority=obj.priority,
            assigned_technician=obj.assigned_technician, user=request.user,
        )
        if target_status != current.status:
            current = change_ticket_status(ticket=current, new_status=target_status, user=request.user)
        obj.__dict__.update(current.__dict__)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "created_at", "from_status", "to_status", "user", "description")
    search_fields = ("ticket__number", "description", "user__username")
    list_filter = ("to_status", "created_at")
    readonly_fields = ("ticket", "created_at", "description", "user", "from_status", "to_status")
    list_select_related = ("ticket", "user")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
