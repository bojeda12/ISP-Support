"""Datos ficticios identificados explícitamente; nunca actualiza registros existentes."""

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from customers.models import Customer, InternetService
from diagnostics.models import DiagnosticRun


class Command(BaseCommand):
    help = "Crea tres clientes, servicios y escenarios ficticios sin modificar datos existentes."

    @transaction.atomic
    def handle(self, *args, **options):
        scenarios = [
            ("001", "Cliente Demo PoE", "poe_disconnected", InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.OFFLINE, DiagnosticRun.Result.FAILED,
             {"poe_power": False}, ""),
            ("002", "Cliente Demo Señal", "weak_signal", InternetService.Status.ACTIVE,
             InternetService.ConnectivityStatus.DEGRADED, DiagnosticRun.Result.DEGRADED,
             {"signal_dbm": -82, "download_mbps": 8}, ""),
            ("003", "Cliente Demo Suspendido", "administrative_suspension", InternetService.Status.SUSPENDED,
             InternetService.ConnectivityStatus.UNKNOWN, DiagnosticRun.Result.UNKNOWN,
             {"administrative_block": True}, "Suspensión ficticia para la demo"),
        ]
        for suffix, name, scenario, status, connectivity, result, metrics, reason in scenarios:
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
            DiagnosticRun.objects.get_or_create(
                internet_service=service, scenario=scenario, source=DiagnosticRun.Source.SIMULATION,
                defaults={"result": result, "metrics": metrics},
            )
        self.stdout.write(self.style.SUCCESS(
            "Demo disponible: 3 clientes, 3 servicios y 3 escenarios simulados. Registros existentes conservados."
        ))
