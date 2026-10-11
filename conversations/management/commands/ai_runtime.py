"""Muestra configuración efectiva sin leer ni imprimir el secreto."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Muestra proveedor/modelos efectivos; no hace llamadas externas.'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps({
            'provider': settings.AI_PROVIDER if settings.AI_PROVIDER in {'demo', 'openai'} else 'unknown',
            'model': settings.OPENAI_MODEL, 'vision_model': settings.OPENAI_VISION_MODEL,
            'key_configured': bool(settings.OPENAI_API_KEY),
            'runtime_logging': settings.DEBUG and settings.DJANGO_ENV == 'development',
            'live_call_performed': False,
        }))
