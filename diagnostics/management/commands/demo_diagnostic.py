import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from customers.models import InternetService
from diagnostics.serializers import DiagnosticRunSerializer
from diagnostics.services import run_diagnostic, set_demo_scenario
from diagnostics.simulation import Scenario


class Command(BaseCommand):
    help = "Cambia opcionalmente un escenario de demo y guarda un diagnóstico simulado. No accede a redes."

    def add_arguments(self, parser):
        parser.add_argument("service_identifier")
        parser.add_argument("--scenario", choices=Scenario.values)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            service = InternetService.objects.get(service_identifier=options["service_identifier"])
            if options["scenario"]:
                set_demo_scenario(internet_service=service, scenario=options["scenario"])
            run = run_diagnostic(internet_service=service)
        except (InternetService.DoesNotExist, ValidationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(DiagnosticRunSerializer(run).data, ensure_ascii=False, indent=2))
