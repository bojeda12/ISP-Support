import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from customers.models import InternetService
from conversations.demo_sessions import issue_demo_session


class Command(BaseCommand):
    help = "Emite una sesión de una hora para un servicio ficticio y un operador autorizado."

    def add_arguments(self, parser):
        parser.add_argument("service_identifier")
        parser.add_argument("--operator", required=True)

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            operator = user_model.objects.get(**{user_model.USERNAME_FIELD: options["operator"]})
            service = InternetService.objects.get(service_identifier=options["service_identifier"])
            session, token = issue_demo_session(operator=operator, internet_service=service)
        except (user_model.DoesNotExist, InternetService.DoesNotExist, PermissionDenied) as error:
            raise CommandError("No se pudo emitir la sesión: verificar modo demo, operador y servicio ficticio.") from error
        self.stdout.write(json.dumps({"token": token, "service_id": service.pk,
                                     "expires_at": session.expires_at.isoformat()}))
