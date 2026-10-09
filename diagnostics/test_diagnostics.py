from dataclasses import replace
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from conversations.models import Conversation
from customers.models import Customer, InternetService
from tickets.models import Ticket
from .engine import evaluate
from .models import DiagnosticRun, SimulationState
from .services import escalation_payload, escalate_diagnostic, run_diagnostic, set_demo_scenario
from .simulation import NetworkMetrics, Scenario, simulate


class EngineTests(SimpleTestCase):
    def test_deterministic_scenarios_and_expected_codes(self):
        for scenario, code in (
            (Scenario.HEALTHY, "NO_FAULT_DETECTED"),
            (Scenario.CPE_OFFLINE, "CPE_UNREACHABLE"),
            (Scenario.WEAK_SIGNAL, "SIGNAL_DEGRADED"),
            (Scenario.LOW_THROUGHPUT, "PERFORMANCE_DEGRADED"),
        ):
            with self.subTest(scenario=scenario):
                metrics = simulate(scenario, 100)
                self.assertEqual(metrics, simulate(scenario, 100))
                self.assertEqual(evaluate(metrics, 100).code, code)

    def test_offline_has_no_invented_measurements(self):
        metrics = simulate(Scenario.CPE_OFFLINE, 100).to_dict()
        self.assertIs(metrics.pop("cpe_online"), False)
        self.assertTrue(all(value is None for value in metrics.values()))

    def test_healthy_scales_with_plan(self):
        self.assertEqual(simulate(Scenario.HEALTHY, 200).download_mbps, 190)

    def test_missing_measurements_are_not_healthy(self):
        self.assertEqual(evaluate(NetworkMetrics(cpe_online=True), 100).code, "INSUFFICIENT_DATA")
        self.assertEqual(evaluate(NetworkMetrics(), 100).code, "INSUFFICIENT_DATA")

    def test_simulation_threshold_boundaries(self):
        baseline = NetworkMetrics(True, -75, 20, 100, 3, 70, "DEMO-AP")
        self.assertEqual(evaluate(baseline, 100).code, "NO_FAULT_DETECTED")
        for values in ({"rssi_dbm": -75.1}, {"snr_db": 19.9}):
            self.assertEqual(evaluate(replace(baseline, **values), 100).code, "SIGNAL_DEGRADED")
        for values in ({"latency_ms": 100.1}, {"packet_loss_percent": 3.1}, {"download_mbps": 69.9}):
            self.assertEqual(evaluate(replace(baseline, **values), 100).code, "PERFORMANCE_DEGRADED")


class DiagnosticFixture:
    def setUp(self):
        self.customer = Customer.objects.create(name="Demo", external_id="TEST-DIAG-CUSTOMER")
        self.service = InternetService.objects.create(
            customer=self.customer, service_identifier="TEST-DIAG-SERVICE", plan_name="Demo",
            advertised_download_mbps=100,
        )
        self.state = SimulationState.objects.create(internet_service=self.service, scenario=Scenario.CPE_OFFLINE)
        self.conversation = Conversation.objects.create(customer=self.customer, internet_service=self.service)

    def run_diagnostic(self):
        return run_diagnostic(internet_service=self.service, conversation=self.conversation)


class DiagnosticServiceTests(DiagnosticFixture, TestCase):
    def test_all_five_scenarios_persist_structured_results(self):
        scenarios = [
            (Scenario.HEALTHY, "NO_FAULT_DETECTED", "PASSED"),
            (Scenario.CPE_OFFLINE, "CPE_UNREACHABLE", "FAILED"),
            (Scenario.WEAK_SIGNAL, "SIGNAL_DEGRADED", "DEGRADED"),
            (Scenario.LOW_THROUGHPUT, "PERFORMANCE_DEGRADED", "DEGRADED"),
            (Scenario.ADMIN_SUSPENDED, "SERVICE_SUSPENDED", "UNKNOWN"),
        ]
        for scenario, code, result in scenarios:
            with self.subTest(scenario=scenario):
                if scenario == Scenario.ADMIN_SUSPENDED:
                    self.service.status = InternetService.Status.SUSPENDED
                    self.service.save()
                set_demo_scenario(internet_service=self.service, scenario=scenario)
                run = self.run_diagnostic()
                run.refresh_from_db()
                self.assertEqual((run.result_code, run.result), (code, result))
                self.assertEqual(run.source, "simulation")
                self.assertEqual(run.conversation, self.conversation)
                self.assertEqual(run.scenario, scenario)
                self.assertEqual(set(run.metrics), set(NetworkMetrics().to_dict()))
                self.assertEqual(run.assessment["code"], code)
                self.assertLessEqual(run.started_at, run.completed_at)
        self.assertEqual(DiagnosticRun.objects.count(), 5)

    @patch("diagnostics.services.simulate")
    def test_suspension_skips_simulator_and_does_not_escalate(self, mocked):
        # El objeto en memoria queda ACTIVE: el servicio debe releer el estado real del ORM.
        InternetService.objects.filter(pk=self.service.pk).update(status="SUSPENDED")
        run = self.run_diagnostic()
        mocked.assert_not_called()
        self.assertEqual(run.result_code, "SERVICE_SUSPENDED")
        self.assertTrue(all(value is None for value in run.metrics.values()))
        self.assertIsNone(escalation_payload(run))
        self.assertIsNone(escalate_diagnostic(run=run))

    @patch("diagnostics.services.simulate")
    def test_cancelled_service_is_not_diagnosed_as_technical_fault(self, mocked):
        InternetService.objects.filter(pk=self.service.pk).update(status="CANCELLED")
        self.assertEqual(self.run_diagnostic().result_code, "SERVICE_INACTIVE")
        mocked.assert_not_called()

    def test_recovery_appends_history_without_changing_administrative_state(self):
        before = self.run_diagnostic()
        set_demo_scenario(internet_service=self.service, scenario=Scenario.HEALTHY)
        after = self.run_diagnostic()
        before.refresh_from_db()
        self.service.refresh_from_db()
        self.assertEqual(before.result_code, "CPE_UNREACHABLE")
        self.assertEqual(after.result_code, "NO_FAULT_DETECTED")
        self.assertIs(before.metrics["cpe_online"], False)
        self.assertIs(after.metrics["cpe_online"], True)
        self.assertEqual(DiagnosticRun.objects.count(), 2)
        self.assertEqual(self.service.status, "ACTIVE")

    def test_escalation_payload_and_ticket_reuse(self):
        run = self.run_diagnostic()
        payload = escalation_payload(run)
        self.assertEqual(payload["customer_id"], str(self.customer.pk))
        self.assertEqual(payload["service_id"], self.service.pk)
        self.assertEqual(payload["suggested_priority"], "HIGH")
        self.assertTrue(payload["recommended_actions"])
        ticket = escalate_diagnostic(run=run)
        self.assertEqual(escalate_diagnostic(run=self.run_diagnostic()).pk, ticket.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(ticket.events.count(), 1)
        self.assertIn("CPE_UNREACHABLE", ticket.description)

    def test_healthy_does_not_escalate_and_missing_conversation_is_rejected(self):
        run = run_diagnostic(internet_service=self.service)
        with self.assertRaises(ValidationError):
            escalate_diagnostic(run=run)
        set_demo_scenario(internet_service=self.service, scenario=Scenario.HEALTHY)
        self.assertIsNone(escalate_diagnostic(run=self.run_diagnostic()))

    def test_wrong_conversation_does_not_save_run(self):
        customer = Customer.objects.create(name="Otro ficticio", external_id="TEST-DIAG-OTHER")
        conversation = Conversation.objects.create(customer=customer)
        with self.assertRaises(ValidationError):
            run_diagnostic(internet_service=self.service, conversation=conversation)
        self.assertEqual(DiagnosticRun.objects.count(), 0)

    def test_unregistered_services_and_invalid_scenarios_are_rejected(self):
        for scenario in ("INVALID", Scenario.ADMIN_SUSPENDED):
            with self.assertRaises(ValidationError):
                set_demo_scenario(internet_service=self.service, scenario=scenario)
        self.state.delete()
        with self.assertRaises(ValidationError):
            self.run_diagnostic()
        with self.assertRaises(ValidationError):
            set_demo_scenario(internet_service=self.service, scenario=Scenario.HEALTHY)

    def test_seed_preserves_modified_scenario_and_existing_history(self):
        call_command("seed_demo", stdout=StringIO())
        service = InternetService.objects.get(service_identifier="DEMO-SERVICE-001")
        set_demo_scenario(internet_service=service, scenario=Scenario.HEALTHY)
        baseline_ids = set(DiagnosticRun.objects.values_list("pk", flat=True))
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(service.simulation_state.scenario, Scenario.HEALTHY)
        self.assertEqual(set(DiagnosticRun.objects.values_list("pk", flat=True)), baseline_ids)
        self.assertEqual(SimulationState.objects.count(), 6)

    def test_demo_command_recovery(self):
        output = StringIO()
        call_command("demo_diagnostic", self.service.service_identifier, scenario="HEALTHY", stdout=output)
        self.assertIn("NO_FAULT_DETECTED", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("demo_diagnostic", "DOES-NOT-EXIST", stdout=StringIO())


class DiagnosticAPITests(DiagnosticFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="demo-operator", is_staff=True)
        self.user.user_permissions.add(Permission.objects.get(codename="run_simulated_diagnostic"))
        self.url = reverse("api:diagnostic-run")

    def test_access_control(self):
        self.assertEqual(self.client.post(self.url, {"service_id": self.service.pk}).status_code, 403)
        no_permission = get_user_model().objects.create_user(username="staff-no-permission", is_staff=True)
        self.client.force_authenticate(no_permission)
        self.assertEqual(self.client.post(self.url, {"service_id": self.service.pk}).status_code, 403)
        no_permission.user_permissions.add(Permission.objects.get(codename="run_simulated_diagnostic"))
        no_permission.is_staff = False
        no_permission.save()
        self.client.force_authenticate(get_user_model().objects.get(pk=no_permission.pk))
        self.assertEqual(self.client.post(self.url, {"service_id": self.service.pk}).status_code, 403)
        self.assertEqual(DiagnosticRun.objects.count(), 0)

    def test_authorized_run_returns_json_and_persists(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, {"service_id": self.service.pk, "conversation_id": self.conversation.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["result_code"], "CPE_UNREACHABLE")
        self.assertIsNone(response.json()["metrics"]["rssi_dbm"])
        self.assertEqual(DiagnosticRun.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_invalid_parameters_missing_service_and_scenario_injection(self):
        self.client.force_authenticate(self.user)
        for data in ({}, {"service_id": 999999}, {"service_id": "invalid"}, {"service_id": 1.5},
                     {"service_id": self.service.pk, "scenario": "HEALTHY"},
                     {"service_id": self.service.pk, "conversation_id": 999999},
                     [1], 3):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.url, data, format="json").status_code, 400)
        self.assertEqual(DiagnosticRun.objects.count(), 0)

    def test_wrong_conversation_and_non_demo_service_are_rejected(self):
        self.client.force_authenticate(self.user)
        other_customer = Customer.objects.create(name="Otro", external_id="TEST-API-OTHER")
        other_conversation = Conversation.objects.create(customer=other_customer)
        response = self.client.post(self.url, {"service_id": self.service.pk, "conversation_id": other_conversation.pk})
        self.assertEqual(response.status_code, 400)
        self.state.delete()
        self.assertEqual(self.client.post(self.url, {"service_id": self.service.pk}).status_code, 400)

    def test_get_is_not_supported(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_session_authentication_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {"service_id": self.service.pk}).status_code, 403)
        self.assertEqual(DiagnosticRun.objects.count(), 0)
