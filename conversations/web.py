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
            destination = reverse('demo-customer') if request.path.startswith('/demo/customer/') else reverse('demo')
            return redirect(f"{reverse('admin:login')}?next={destination}")
        if not operator_allowed(request.user):
            raise PermissionDenied("Demo operator permission is required.")
        return view(request, *args, **kwargs)
    return never_cache(guarded)


def current_state(request):
    from .quick_replies import offers
    session = DemoChatSession.objects.select_related("internet_service__customer").filter(
        pk=request.session.get("demo_session_id"), operator=request.user,
        revoked=False, expires_at__gt=timezone.now(),
    ).first()
    if session is None or not is_demo_service(session.internet_service):
        return {"service": None, "conversation_id": None, "language": request.session.get("demo_preferred_language"), "language_confirmed": request.session.get("demo_preferred_language") in {"en", "es"}, "time_zone": settings.TIME_ZONE}
    conversation = Conversation.objects.filter(
        pk=request.session.get("demo_conversation_id"), internet_service=session.internet_service,
        customer_id=session.internet_service.customer_id,
    ).first()
    return {
        "service": {"id": session.internet_service_id, "identifier": session.internet_service.service_identifier,
                    "plan": session.internet_service.plan_name},
        "conversation_id": conversation.pk if conversation else None,
        "conversation_status": conversation.status if conversation else None,
        "language": conversation.language if conversation else request.session.get("demo_preferred_language", "en"),
        "language_confirmed": bool(conversation) or request.session.get("demo_preferred_language") in {"en", "es"},
        "preferred_language": request.session.get("demo_preferred_language"),
        "time_zone": settings.TIME_ZONE,
        "expires_at": session.expires_at.isoformat(),
        "quick_replies": offers(),
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
@require_GET
def customer_page(request):
    """Vista previa local del widget; conserva la autorización del operador."""
    response = render(request, 'conversations/demo.html', {'customer_mode': True})
    response['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    return response


@demo_operator
@require_GET
def customer_state(request):
    return JsonResponse(current_state(request))


@demo_operator
@require_POST
def customer_reconnect(request):
    previous = DemoChatSession.objects.select_related('internet_service__customer').filter(
        pk=request.session.get('demo_session_id'), operator=request.user).first()
    if previous is None or not is_demo_service(previous.internet_service):
        return JsonResponse({'error': 'An authorized service session is required.'}, status=403)
    # El navegador no selecciona ni sustituye la identidad o el servicio.
    request.POST = request.POST.copy()
    request.POST['service_id'] = str(previous.internet_service_id)
    return select_demo_service(request)


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
    state = current_state(request)
    if settings.DEBUG and settings.DJANGO_ENV == 'development':
        import os
        state['runtime'] = {'provider':settings.AI_PROVIDER,
            'model':settings.OPENAI_MODEL,'vision_model':settings.OPENAI_VISION_MODEL,
            'key_configured':bool(settings.OPENAI_API_KEY),
            'inconclusive_review':settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW,
            'process_id':os.getpid(),'progress_policy_version':2,'completion_policy_version':1}
    return JsonResponse(state)


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
    previous_session = DemoChatSession.objects.filter(pk=previous_id,operator=request.user,internet_service=service).first() if previous_id else None
    retained = Conversation.objects.filter(pk=request.session.get('demo_conversation_id'),
        internet_service=service,customer=service.customer).first() if previous_session else None
    if previous_session is None:
        # Tras volver a autenticar, recuperar únicamente el último turno de este
        # operador y servicio; nunca adivinar conversaciones de otros operadores.
        from .models import ChatTurn
        latest_id = ChatTurn.objects.filter(session__operator=request.user,
            session__internet_service=service).order_by('-created_at').values_list('response__conversation_id',flat=True).first()
        retained = Conversation.objects.filter(pk=latest_id,internet_service=service,
            customer=service.customer).first() if latest_id else None
    session, _ = issue_demo_session(operator=request.user, internet_service=service)
    if previous_id:
        DemoChatSession.objects.filter(pk=previous_id, operator=request.user).update(revoked=True)
    request.session["demo_session_id"] = str(session.pk)
    if retained:
        request.session['demo_conversation_id'] = retained.pk
    if request.session.get("demo_conversation_id") and not retained:
        request.session.pop("demo_preferred_language", None)
    if not retained:
        request.session.pop("demo_conversation_id", None)
    return JsonResponse(current_state(request))


def selectable_conversations(request, service):
    """Historial del operador actual, siempre acotado al servicio autorizado."""
    from .models import ChatTurn
    ids = ChatTurn.objects.filter(session__operator=request.user,
        session__internet_service=service).values_list('response__conversation_id', flat=True)
    return Conversation.objects.filter(pk__in=ids, internet_service=service,
        customer_id=service.customer_id).order_by('-created_at', '-pk')


@demo_operator
@require_GET
def previous_conversations(request):
    state = current_state(request)
    if not state['service']:
        return JsonResponse({'error': 'Reconnect the service.'}, status=403)
    service = InternetService.objects.get(pk=state['service']['id'])
    try:
        offset = int(request.GET.get('offset', '0'))
        if offset < 0:
            raise ValueError
    except ValueError:
        return JsonResponse({'error': 'Invalid cursor.'}, status=400)
    rows = list(selectable_conversations(request, service)[offset:offset + 51])
    return JsonResponse({'conversations': [{'id': c.pk, 'language': c.language,
        'status': c.status, 'created_at': c.created_at.isoformat()} for c in rows[:50]],
        'next_offset': offset + 50 if len(rows) > 50 else None})


@demo_operator
@require_POST
def choose_conversation(request):
    state = current_state(request)
    if not state['service']:
        return JsonResponse({'error': 'Reconnect the service.'}, status=403)
    if request.POST.get('action') == 'new':
        # Creación diferida al primer turno; nunca borrar mensajes ni copiar hechos.
        request.session.pop('demo_conversation_id', None)
        return JsonResponse(current_state(request))
    service = InternetService.objects.get(pk=state['service']['id'])
    try:
        conversation_id = int(request.POST.get('conversation_id', ''))
    except ValueError:
        return JsonResponse({'error': 'Invalid conversation.'}, status=400)
    conversation = selectable_conversations(request, service).filter(pk=conversation_id).first()
    if conversation is None:
        raise Http404
    request.session['demo_conversation_id'] = conversation.pk
    return JsonResponse(current_state(request))
