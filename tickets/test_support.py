from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import RequestFactory
from django.contrib import admin
from django.urls import reverse

from conversations.models import Conversation, Message
from customers.models import Customer, InternetService
from diagnostics.models import DiagnosticRun
from .models import Ticket, TicketEvent
from .services import change_ticket_status, create_ticket, update_ticket_details


class SupportTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Cliente Ficticio", external_id="TEST-CUST-01")
        self.service = InternetService.objects.create(
            customer=self.customer, service_identifier="TEST-SVC-01",
            plan_name="Demo", advertised_download_mbps=100,
        )
        self.conversation = Conversation.objects.create(customer=self.customer, internet_service=self.service)
        self.user = get_user_model().objects.create_user(username="test-technician")

    def ticket(self, **kwargs):
        data = dict(
            customer=self.customer, internet_service=self.service, conversation=self.conversation,
            incident_key="poe-disconnected", title="PoE desconectado", description="Incidencia ficticia",
        )
        data.update(kwargs)
        return create_ticket(**data)

    def test_customer_has_multiple_services_and_independent_statuses(self):
        other = InternetService.objects.create(
            customer=self.customer, service_identifier="TEST-SVC-02", plan_name="Demo",
            advertised_download_mbps=200, status=InternetService.Status.SUSPENDED,
            connectivity_status=InternetService.ConnectivityStatus.ONLINE,
        )
        self.assertEqual(self.customer.services.count(), 2)
        self.assertNotEqual(str(self.customer.pk), self.customer.external_id)
        self.assertEqual(other.status, "SUSPENDED")
        self.assertEqual(other.connectivity_status, "ONLINE")

    def test_conversations_and_messages_are_chronological(self):
        Conversation.objects.create(customer=self.customer)
        first = Message.objects.create(conversation=self.conversation, sender=Message.Sender.CUSTOMER, content="Hola")
        second = Message.objects.create(conversation=self.conversation, sender=Message.Sender.SYSTEM, content="Recibido")
        self.assertEqual(list(self.conversation.messages.all()), [first, second])
        self.assertEqual(self.customer.conversations.count(), 2)

    def test_creation_records_event(self):
        ticket = self.ticket(user=self.user)
        self.assertEqual(ticket.status, Ticket.Status.OPEN)
        self.assertTrue(ticket.number.startswith("ISP-"))
        event = ticket.events.get()
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.to_status, "OPEN")

    def test_valid_transitions_and_authorized_closure(self):
        self.user.user_permissions.add(Permission.objects.get(codename="close_ticket"))
        ticket = self.ticket()
        for status in (Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            ticket = change_ticket_status(ticket=ticket, new_status=status, user=self.user)
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(list(ticket.events.values_list("to_status", flat=True)),
                         ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"])
        self.assertEqual(ticket.events.last().from_status, "RESOLVED")
        self.assertEqual(ticket.events.last().user, self.user)

    def test_invalid_transition_does_not_change_ticket_or_history(self):
        ticket = self.ticket()
        for status in ("RESOLVED", "CLOSED", "INVALID", "OPEN"):
            with self.assertRaises(ValidationError):
                change_ticket_status(ticket=ticket, new_status=status, user=self.user)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "OPEN")
        self.assertEqual(ticket.events.count(), 1)

    def test_close_requires_permission(self):
        ticket = self.ticket()
        ticket = change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="RESOLVED")
        for user in (None, self.user):
            with self.assertRaises(PermissionDenied):
                change_ticket_status(ticket=ticket, new_status="CLOSED", user=user)
        self.assertEqual(ticket.events.count(), 3)

    def test_reopen_clears_resolution_timestamp(self):
        ticket = change_ticket_status(ticket=self.ticket(), new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="RESOLVED")
        ticket = change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
        self.assertIsNone(ticket.resolved_at)

    def test_duplicate_creation_returns_original_with_single_event(self):
        first = self.ticket()
        duplicate = self.ticket(incident_key=" POE-DISCONNECTED ", title="Reintento")
        self.assertEqual(first.pk, duplicate.pk)
        first = change_ticket_status(ticket=first, new_status="IN_PROGRESS")
        self.assertEqual(self.ticket().pk, first.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketEvent.objects.count(), 2)

    def test_different_incidents_and_resolved_incidents_allow_new_ticket(self):
        first = self.ticket()
        self.assertNotEqual(self.ticket(incident_key="weak-signal").pk, first.pk)
        first = change_ticket_status(ticket=first, new_status="IN_PROGRESS")
        change_ticket_status(ticket=first, new_status="RESOLVED")
        self.assertNotEqual(self.ticket().pk, first.pk)

    def test_database_constraint_prevents_active_duplicates(self):
        first = self.ticket()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.create(
                customer=self.customer, internet_service=self.service, conversation=self.conversation,
                incident_key=first.incident_key, title="Duplicado", description="Prueba",
            )

    def test_relationships_reject_wrong_customer_and_service(self):
        other_customer = Customer.objects.create(name="Otro ficticio", external_id="TEST-CUST-02")
        with self.assertRaises(ValidationError):
            Conversation.objects.create(customer=other_customer, internet_service=self.service)
        with self.assertRaises(ValidationError):
            self.ticket(customer=other_customer)
        other_service = InternetService.objects.create(
            customer=self.customer, service_identifier="TEST-SVC-03", plan_name="Demo", advertised_download_mbps=50
        )
        with self.assertRaises(ValidationError):
            self.ticket(internet_service=other_service)
        with self.assertRaises(ValidationError):
            DiagnosticRun.objects.create(internet_service=other_service, conversation=self.conversation, scenario="test")

    def test_seed_is_idempotent_and_preserves_existing_data(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        customer = Customer.objects.get(external_id="DEMO-CUSTOMER-001")
        customer.name = "Nombre demo editado"
        customer.save()
        call_command("seed_demo", stdout=out)
        self.assertEqual(Customer.objects.count(), 6)
        self.assertEqual(InternetService.objects.count(), 6)
        self.assertEqual(DiagnosticRun.objects.count(), 5)
        customer.refresh_from_db()
        self.assertEqual(customer.name, "Nombre demo editado")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Cliente Ficticio")

    def test_admin_changes_status_and_records_actor(self):
        actor = get_user_model().objects.create_superuser(username="test-admin")
        self.client.force_login(actor)
        ticket = self.ticket()
        response = self.client.post(reverse("admin:tickets_ticket_change", args=[ticket.pk]), {
            "title": ticket.title, "description": ticket.description, "priority": ticket.priority,
            "status": "IN_PROGRESS", "assigned_technician": "",
            "events-TOTAL_FORMS": "1", "events-INITIAL_FORMS": "1",
            "events-MIN_NUM_FORMS": "0", "events-MAX_NUM_FORMS": "1000",
            "events-0-id": ticket.events.get().pk, "events-0-ticket": ticket.pk,
            "_save": "Guardar",
        })
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "IN_PROGRESS")
        self.assertEqual(ticket.events.last().user, actor)

    def test_admin_form_rejects_invalid_transition_and_unauthorized_closure(self):
        ticket = self.ticket()
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = admin.site._registry[Ticket]
        form_class = model_admin.get_form(request, ticket)
        data = {"title": ticket.title, "description": ticket.description,
                "priority": ticket.priority, "status": "CLOSED"}
        form = form_class(data=data, instance=ticket)
        self.assertFalse(form.is_valid())
        self.assertIn("status", form.errors)
        ticket = change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="RESOLVED")
        form = form_class(data=data, instance=ticket)
        self.assertFalse(form.is_valid())
        self.assertIn("status", form.errors)
        self.assertEqual(ticket.events.count(), 3)

    def test_reopen_cannot_conflict_with_another_active_ticket(self):
        ticket = change_ticket_status(ticket=self.ticket(), new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="RESOLVED")
        self.ticket()
        with self.assertRaises(ValidationError):
            change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "RESOLVED")
        self.assertEqual(ticket.events.count(), 3)

    def test_closed_is_terminal_and_in_progress_can_return_to_open(self):
        self.user.user_permissions.add(Permission.objects.get(codename="close_ticket"))
        ticket = change_ticket_status(ticket=self.ticket(), new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="OPEN")
        ticket = change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
        ticket = change_ticket_status(ticket=ticket, new_status="RESOLVED")
        ticket = change_ticket_status(ticket=ticket, new_status="CLOSED", user=self.user)
        for status in Ticket.Status.values:
            with self.assertRaises(ValidationError):
                change_ticket_status(ticket=ticket, new_status=status, user=self.user)

    def test_seed_reserved_identifier_conflict_preserves_unrelated_records(self):
        Customer.objects.create(name="Registro ajeno", external_id="DEMO-CUSTOMER-002")
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual(InternetService.objects.count(), 1)
        self.assertEqual(DiagnosticRun.objects.count(), 0)

    def test_no_public_ticket_mutation_routes(self):
        self.assertEqual(self.client.post("/api/tickets/", {}).status_code, 404)

    def test_assignment_and_priority_changes_record_event_only_when_changed(self):
        ticket = self.ticket()
        values = dict(ticket=ticket, title=ticket.title, description=ticket.description,
                      priority=Ticket.Priority.HIGH, assigned_technician=self.user, user=self.user)
        updated = update_ticket_details(**values)
        update_ticket_details(**values)
        self.assertEqual(updated.assigned_technician, self.user)
        self.assertEqual(updated.priority, "HIGH")
        self.assertEqual(ticket.events.count(), 2)
        self.assertIn("assigned_technician", ticket.events.last().description)
        self.assertEqual(ticket.events.last().user, self.user)
