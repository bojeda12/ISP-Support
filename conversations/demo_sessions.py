"""Sesiones opacas, temporales y limitadas a los cinco servicios ficticios del seed."""

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import DemoChatSession


def demo_enabled() -> bool:
    return settings.ENABLE_DEMO_CHAT and settings.DEBUG and settings.DJANGO_ENV in {"development", "test"}


def is_demo_service(service) -> bool:
    suffix = service.service_identifier.removeprefix("DEMO-SERVICE-")
    return (
        suffix in {"001", "002", "003", "004", "005"}
        and service.service_identifier == f"DEMO-SERVICE-{suffix}"
        and service.customer.external_id == f"DEMO-CUSTOMER-{suffix}"
        and service.customer_id == uuid.UUID(f"00000000-0000-4000-8000-000000000{suffix}")
        and hasattr(service, "simulation_state")
    )


def operator_allowed(operator) -> bool:
    return operator.is_active and operator.is_staff and operator.has_perm("conversations.use_demo_chat")


def issue_demo_session(*, operator, internet_service):
    if not demo_enabled() or not operator_allowed(operator) or not is_demo_service(internet_service):
        raise PermissionDenied("Demo session is not authorized.")
    token = secrets.token_urlsafe(32)
    session = DemoChatSession.objects.create(
        operator=operator, internet_service=internet_service,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return session, token
