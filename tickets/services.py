"""Operaciones de tickets; los adaptadores deben utilizar estas funciones."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from conversations.models import Conversation
from .models import Ticket, TicketEvent


TRANSITIONS = {
    Ticket.Status.OPEN: {Ticket.Status.IN_PROGRESS},
    Ticket.Status.IN_PROGRESS: {Ticket.Status.OPEN, Ticket.Status.RESOLVED},
    Ticket.Status.RESOLVED: {Ticket.Status.IN_PROGRESS, Ticket.Status.CLOSED},
    Ticket.Status.CLOSED: set(),
}


def validate_transition(ticket, new_status, user=None):
    if new_status not in TRANSITIONS.get(ticket.status, set()):
        raise ValidationError({"status": f"Invalid transition: {ticket.status} -> {new_status}"})
    if new_status == Ticket.Status.CLOSED and (
        user is None or not user.is_authenticated or not user.has_perm("tickets.close_ticket")
    ):
        raise PermissionDenied("Closing tickets requires tickets.close_ticket permission.")


@transaction.atomic
def create_ticket(*, customer, internet_service, incident_key, title, description,
                  conversation=None, priority=Ticket.Priority.MEDIUM,
                  assigned_technician=None, user=None):
    incident_key = incident_key.strip().lower()
    candidate = Ticket(
        customer=customer, internet_service=internet_service, conversation=conversation,
        incident_key=incident_key, title=title, description=description, priority=priority,
        assigned_technician=assigned_technician,
    )
    candidate.full_clean(validate_unique=False, validate_constraints=False)
    if conversation is not None:
        # Serializa creaciones de la misma conversación en PostgreSQL.
        Conversation.objects.select_for_update().get(pk=conversation.pk)
        ticket, created = Ticket.objects.get_or_create(
            conversation=conversation, incident_key=incident_key,
            status__in=[Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS],
            defaults={
                "customer": customer, "internet_service": internet_service,
                "title": title, "description": description, "priority": priority,
                "assigned_technician": assigned_technician,
            },
        )
        if ticket.internet_service_id != internet_service.pk:
            raise ValidationError("The existing incident belongs to another service.")
    else:
        candidate.save()
        ticket, created = candidate, True
    if created:
        TicketEvent.objects.create(
            ticket=ticket, description="Ticket created", user=user, to_status=Ticket.Status.OPEN
        )
    return ticket


@transaction.atomic
def change_ticket_status(*, ticket, new_status, user=None):
    current = Ticket.objects.select_for_update().get(pk=ticket.pk)
    validate_transition(current, new_status, user)
    old_status = current.status
    current.status = new_status
    current.resolved_at = (
        timezone.now() if new_status == Ticket.Status.RESOLVED else
        current.resolved_at if new_status == Ticket.Status.CLOSED else None
    )
    current.full_clean()
    current.save(update_fields=["status", "resolved_at", "updated_at"])
    TicketEvent.objects.create(
        ticket=current, user=user, description=f"Status changed: {old_status} -> {new_status}",
        from_status=old_status, to_status=new_status,
    )
    return current


@transaction.atomic
def update_ticket_details(*, ticket, title, description, priority, assigned_technician, user=None):
    current = Ticket.objects.select_for_update().get(pk=ticket.pk)
    values = dict(title=title, description=description, priority=priority,
                  assigned_technician=assigned_technician)
    changed_fields = [field for field, value in values.items() if getattr(current, field) != value]
    if changed_fields:
        for field, value in values.items():
            setattr(current, field, value)
        current.full_clean()
        current.save(update_fields=[*changed_fields, "updated_at"])
        TicketEvent.objects.create(
            ticket=current, user=user, description=f"Ticket updated: {', '.join(changed_fields)}"
        )
    return current
