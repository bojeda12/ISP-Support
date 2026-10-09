import hashlib

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, SessionAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .demo_sessions import demo_enabled, is_demo_service, operator_allowed
from .models import DemoChatSession


class DemoSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if not demo_enabled():
            raise AuthenticationFailed("Demo chat is disabled.")
        parts = get_authorization_header(request).split()
        sessions = DemoChatSession.objects.select_related("operator", "internet_service__customer").filter(
            revoked=False, expires_at__gt=timezone.now()
        )
        if not parts and request.session.get("demo_session_id"):
            # Variante web: cookie Django autenticada y CSRF para operaciones mutables.
            authenticated = SessionAuthentication().authenticate(request)
            if authenticated is None:
                raise AuthenticationFailed("Operator login is required.")
            session = sessions.filter(pk=request.session["demo_session_id"], operator=authenticated[0]).first()
        else:
            if len(parts) != 2 or parts[0].lower() != b"demo" or len(parts[1]) > 128:
                raise AuthenticationFailed("A valid demo session is required.")
            digest = hashlib.sha256(parts[1]).hexdigest()
            session = sessions.filter(token_digest=digest).first()
        if session is None or not operator_allowed(session.operator) or not is_demo_service(session.internet_service):
            raise AuthenticationFailed("Demo session is expired, revoked or unauthorized.")
        return session.operator, session

    def authenticate_header(self, request):
        return "Demo"
