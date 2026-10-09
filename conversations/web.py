"""Acceso web de operadores: autorización local y ninguna credencial en JavaScript."""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings

from customers.models import InternetService
from .demo_sessions import demo_enabled, is_demo_service, issue_demo_session, operator_allowed
from .models import Conversation, DemoChatSession


def demo_operator(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not demo_enabled():
            raise Http404
        if not request.user.is_authenticated:
            return redirect(f"{reverse('admin:login')}?next={reverse('demo')}")
        if not operator_allowed(request.user):
            raise PermissionDenied("Demo operator permission is required.")
        return view(request, *args, **kwargs)
    return never_cache(guarded)


def current_state(request):
    session = DemoChatSession.objects.select_related("internet_service__customer").filter(
        pk=request.session.get("demo_session_id"), operator=request.user,
        revoked=False, expires_at__gt=timezone.now(),
    ).first()
    if session is None or not is_demo_service(session.internet_service):
        return {"service": None, "conversation_id": None, "language": request.session.get("demo_preferred_language"), "language_confirmed": request.session.get("demo_preferred_language") in {"en", "es"}, "time_zone": settings.TIME_ZONE}
    conversation = Conversation.objects.filter(
        pk=request.session.get("demo_conversation_id"), internet_service=session.internet_service,
        customer_id=session.internet_service.customer_id, status="OPEN",
    ).first()
    return {
        "service": {"id": session.internet_service_id, "identifier": session.internet_service.service_identifier,
                    "plan": session.internet_service.plan_name},
        "conversation_id": conversation.pk if conversation else None,
        "language": conversation.language if conversation else request.session.get("demo_preferred_language", "en"),
        "language_confirmed": bool(conversation) or request.session.get("demo_preferred_language") in {"en", "es"},
        "preferred_language": request.session.get("demo_preferred_language"),
        "time_zone": settings.TIME_ZONE,
        "expires_at": session.expires_at.isoformat(),
    }


@demo_operator
@require_GET
def demo_page(request):
    services = [service for service in InternetService.objects.select_related("customer")
                .filter(service_identifier__startswith="DEMO-SERVICE-") if is_demo_service(service)]
    response = render(request, "conversations/demo.html", {"services": services})
    response["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@demo_operator
@require_POST
def confirm_demo_language(request):
    language = request.POST.get("language")
    if language not in {"en", "es"}:
        return JsonResponse({"error": "Choose English or Spanish."}, status=400)
    request.session["demo_preferred_language"] = language
    return JsonResponse({"language": language, "language_confirmed": True})


@demo_operator
@require_GET
def demo_state(request):
    return JsonResponse(current_state(request))


@demo_operator
@require_POST
def select_demo_service(request):
    try:
        service_id = int(request.POST.get("service_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid service."}, status=400)
    service = InternetService.objects.select_related("customer").filter(pk=service_id).first()
    if service is None or not is_demo_service(service):
        return JsonResponse({"error": "Service is not available."}, status=400)
    previous_id = request.session.get("demo_session_id")
    session, _ = issue_demo_session(operator=request.user, internet_service=service)
    if previous_id:
        DemoChatSession.objects.filter(pk=previous_id, operator=request.user).update(revoked=True)
    request.session["demo_session_id"] = str(session.pk)
    if request.session.get("demo_conversation_id"):
        request.session.pop("demo_preferred_language", None)
    request.session.pop("demo_conversation_id", None)
    return JsonResponse(current_state(request))
