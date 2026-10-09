"""Datos ficticios identificados explícitamente; nunca actualiza registros existentes."""

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from customers.models import Customer, InternetService
from diagnostics.models import DiagnosticRun, SimulationState
from diagnostics.simulation import Scenario
from diagnostics.services import run_diagnostic


class Command(BaseCommand):
    help = "Crea cinco clientes, servicios y escenarios ficticios sin modificar datos existentes."

    @transaction.atomic
    def handle(self, *args, **options):
        scenarios = [
            ("001", "Cliente Demo PoE", Scenario.CPE_OFFLINE, InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.OFFLINE, ""),
            ("002", "Cliente Demo Señal", Scenario.WEAK_SIGNAL, InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.DEGRADED, ""),
            ("003", "Cliente Demo Suspendido", Scenario.ADMIN_SUSPENDED, InternetService.Status.SUSPENDED,
             InternetService.ConnectivityStatus.UNKNOWN, "Suspensión ficticia para la demo"),
            ("004", "Cliente Demo Sano", Scenario.HEALTHY, InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.ONLINE, ""),
            ("005", "Cliente Demo Rendimiento", Scenario.LOW_THROUGHPUT, InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.DEGRADED, ""),
        ]
        for suffix, name, scenario, status, connectivity, reason in scenarios:
            external_id = f"DEMO-CUSTOMER-{suffix}"
            customer_id = uuid.UUID(f"00000000-0000-4000-8000-000000000{suffix}")
            customer, _ = Customer.objects.get_or_create(
                external_id=external_id, defaults={"id": customer_id, "name": name}
            )
            if customer.pk != customer_id:
                raise CommandError(f"Identificador reservado ocupado: {external_id}; no se modificaron datos.")
            identifier = f"DEMO-SERVICE-{suffix}"
            service, _ = InternetService.objects.get_or_create(
                service_identifier=identifier,
                defaults={
                    "customer": customer, "plan_name": "Demo 100 Mbps", "advertised_download_mbps": 100,
                    "status": status, "connectivity_status": connectivity,
                    "suspension_reason": reason, "cpe_identifier": f"DEMO-CPE-{suffix}",
                },
            )
            if service.customer_id != customer_id:
                raise CommandError(f"Identificador reservado ocupado: {identifier}; no se modificaron datos.")
            SimulationState.objects.get_or_create(
                internet_service=service,
                defaults={"scenario": scenario},
            )
            if not DiagnosticRun.objects.filter(
                internet_service=service, source=DiagnosticRun.Source.SIMULATION
            ).exists():
                run_diagnostic(internet_service=service)
        self.stdout.write(self.style.SUCCESS(
            "Demo disponible: 5 clientes, 5 servicios y 5 escenarios simulados. Registros existentes conservados."
        ))
