import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def generate_ticket_number():
    return f"ISP-{uuid.uuid4().hex[:12].upper()}"


class Ticket(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=36, unique=True, default=generate_ticket_number, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="tickets")
    internet_service = models.ForeignKey("customers.InternetService", on_delete=models.PROTECT, related_name="tickets")
    conversation = models.ForeignKey(
        "conversations.Conversation", on_delete=models.PROTECT, related_name="tickets", null=True, blank=True
    )
    incident_key = models.SlugField(max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status, default=Status.OPEN)
    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="assigned_tickets", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(
            fields=["conversation", "incident_key"],
            condition=models.Q(status__in=["OPEN", "IN_PROGRESS"]),
            name="unique_active_conversation_incident",
        )]
        permissions = [("close_ticket", "Puede cerrar tickets")]

    def clean(self):
        super().clean()
        errors = {}
        if self.internet_service_id and self.internet_service.customer_id != self.customer_id:
            errors["internet_service"] = "Service must belong to the customer."
        if self.conversation_id:
            conversation = self.conversation
            if (conversation.customer_id != self.customer_id or
                    conversation.internet_service_id not in (None, self.internet_service_id)):
                errors["conversation"] = "Conversation must match the service and customer."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.number} - {self.title}"

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class TicketEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    from_status = models.CharField(max_length=12, choices=Ticket.Status, blank=True)
    to_status = models.CharField(max_length=12, choices=Ticket.Status, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.ticket.number}: {self.description}"
