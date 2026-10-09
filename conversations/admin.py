from django.contrib import admin
from .models import Conversation, DemoChatSession, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("sender", "content", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "internet_service", "language", "status", "created_at")
    search_fields = ("customer__name", "customer__external_id", "internet_service__service_identifier")
    list_filter = ("status", "language", "created_at")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("customer", "internet_service")
    inlines = (MessageInline,)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("customer", "internet_service") if obj else ())


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "created_at")
    search_fields = ("content", "conversation__customer__external_id")
    list_filter = ("sender", "created_at")
    readonly_fields = ("created_at", "metadata")
    list_select_related = ("conversation__customer",)


@admin.register(DemoChatSession)
class DemoChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "operator", "internet_service", "expires_at", "revoked")
    list_filter = ("revoked", "expires_at")
    search_fields = ("operator__username", "internet_service__service_identifier")
    fields = ("id", "operator", "internet_service", "created_at", "expires_at", "revoked")
    readonly_fields = ("id", "operator", "internet_service", "created_at", "expires_at")

    def has_add_permission(self, request):
        return False
