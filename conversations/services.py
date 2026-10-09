"""Orquestador: clasificar fuera de la transacción y ejecutar solo políticas explícitas."""

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from pydantic import ValidationError as SchemaValidationError

from diagnostics.services import escalate_diagnostic, run_diagnostic
from .ai import Interpretation, Intent, ProviderError, detect_language, get_provider
from .demo_sessions import demo_enabled, is_demo_service, operator_allowed
from .models import Conversation, Message
from .replies import diagnostic_payload, reply
from .instructions import relevant_images
from .instructions import catalog
from .context import conversation_context, contextual_reply, remember_claim

logger = logging.getLogger(__name__)


def bounded_history(conversation, before_message_id: int) -> list[dict]:
    messages = conversation.messages.filter(pk__lt=before_message_id).order_by("-created_at", "-pk")[:settings.CHAT_HISTORY_MESSAGES]
    history, remaining = [], settings.CHAT_HISTORY_CHARACTERS
    for message in messages:
        if message.sender not in {Message.Sender.CUSTOMER, Message.Sender.ASSISTANT}:
            continue
        content = message.content[:min(1000, remaining)]
        if not content:
            break
        history.append({"role": message.sender, "content": content})
        remaining -= len(content)
    return list(reversed(history))


def ensure_session(session):
    from django.utils import timezone

    if (not demo_enabled() or session.revoked or session.expires_at <= timezone.now()
            or not operator_allowed(session.operator) or not is_demo_service(session.internet_service)):
        raise PermissionDenied("Demo session is not authorized.")


def chat(*, session, message: str, conversation=None, language=None, initial_language=None) -> dict:
    ensure_session(session)
    message = message.strip()
    if not message or len(message) > settings.CHAT_MAX_MESSAGE_LENGTH:
        raise ValidationError("Invalid message length.")
    if language not in (None, "es", "en"):
        raise ValidationError("Unsupported language.")
    # El mensaje se confirma antes de llamar al proveedor: sus errores no borran el historial.
    with transaction.atomic():
        if conversation is None:
            conversation = Conversation.objects.create(
                customer=session.internet_service.customer, internet_service=session.internet_service,
                language=language or detect_language(message, initial_language or "es"),
            )
        else:
            conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if (conversation.customer_id != session.internet_service.customer_id or
                conversation.internet_service_id != session.internet_service_id):
            raise PermissionDenied("Conversation is outside the authorized service.")
        if conversation.status != Conversation.Status.OPEN:
            raise ValidationError("Conversation is closed.")
        selected_language = language or detect_language(message, conversation.language)
        user_message = Message.objects.create(
            conversation=conversation, sender=Message.Sender.CUSTOMER, content=message
        )
    provider_status = "ok"
    context = conversation_context(conversation)
    try:
        history = bounded_history(conversation, user_message.pk)
        # Un resumen estructurado sustituye una entrada, manteniendo los límites existentes.
        history = [{"role": "context", "content": "", "context": context}] + history[:max(0, settings.CHAT_HISTORY_MESSAGES - 1)]
        raw = get_provider().interpret(
            message=message, history=history, language=selected_language
        )
        interpreted = Interpretation.model_validate(raw)
        selected_language = language or interpreted.language
    except (ProviderError, SchemaValidationError, TimeoutError) as error:
        known_reasons = {"configuration_missing", "invalid_or_refused_output", "timeout", "upstream_error", "invalid_output", "unknown_provider"}
        reason = str(error) if isinstance(error, ProviderError) and str(error) in known_reasons else type(error).__name__
        logger.warning("Chat provider failure conversation=%s reason=%s", conversation.pk, reason)
        interpreted = Interpretation(intent=Intent.OTHER, language=selected_language)
        provider_status = "unavailable"

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        context = conversation_context(conversation)
        conversation.language = selected_language
        conversation.save(update_fields=["language", "updated_at"])
        intent = interpreted.intent
        response_text = reply("other", selected_language)
        requires_action, diagnostic, ticket = "DESCRIBE_PROBLEM", None, None
        reported_actions = []
        display_key = None
        contextual = {Intent.EQUIPMENT_CLARIFICATION, Intent.REPORT_INDICATORS,
            Intent.CLARIFY_COMPLETED_CHECKS, Intent.EXPLAIN_POE, Intent.REQUEST_PHOTO, Intent.PHOTO_QUESTION}
        if provider_status != "ok":
            response_text = reply("unavailable", selected_language)
            requires_action = "RETRY_MESSAGE"
        elif intent == Intent.GREETING:
            response_text, requires_action = reply("greeting", selected_language), "DESCRIBE_PROBLEM"
        elif intent == Intent.CHECK_SERVICE_STATUS:
            service = session.internet_service
            service.refresh_from_db()
            key = "SERVICE_SUSPENDED" if service.status == "SUSPENDED" else "SERVICE_INACTIVE" if service.status != "ACTIVE" else "service_status"
            response_text = reply(key, selected_language, status=service.status)
            requires_action = "CONTACT_ADMINISTRATION" if service.status != "ACTIVE" else "NONE"
        elif intent == Intent.CHECK_TICKET:
            ticket = conversation.tickets.order_by("-created_at").first()
            response_text = reply("ticket_status", selected_language, number=ticket.number, status=ticket.status) if ticket else reply("no_ticket", selected_language)
            requires_action = "NONE"
        elif intent in contextual or (intent == Intent.OTHER and context['reported_issue']):
            if intent in {Intent.EQUIPMENT_CLARIFICATION, Intent.REPORT_INDICATORS, Intent.CLARIFY_COMPLETED_CHECKS}:
                remember_claim(context, message, intent.value)
            if intent == Intent.EQUIPMENT_CLARIFICATION:
                context['equipment_claim'] = {'text': message[:300], 'verified': False}
            response_text = contextual_reply(intent.value, context, selected_language)
            requires_action = "CLARIFY_CONTEXT"
            context['unresolved_questions'] = [intent.value]
        elif intent == Intent.GUIDE_REQUEST:
            response_text = ("Here are the generic demonstration instructions. Equipment varies; use only steps applicable to your identified device." if selected_language == 'en' else
                             "Estas son las instrucciones genéricas de demostración. Los equipos varían; usa solo los pasos aplicables al dispositivo identificado.")
            requires_action = "REVIEW_GUIDE"
        elif intent in {Intent.NO_INTERNET, Intent.SLOW_INTERNET, Intent.REQUEST_TECHNICIAN, Intent.CONFIRM_PHYSICAL_CHECK}:
            previous = conversation.diagnostic_runs.order_by("-created_at", "-pk").first()
            can_recheck = previous is not None and previous.result_code == "CPE_UNREACHABLE"
            if intent == Intent.CONFIRM_PHYSICAL_CHECK and not can_recheck:
                response_text = reply("no_previous_check", selected_language)
            else:
                if intent == Intent.CONFIRM_PHYSICAL_CHECK:
                    reported_actions = ["Customer reports checking PoE and accessible connections; not independently verified." if 'poe' in message.lower() else
                                        "Customer reports completed accessible physical checks; not independently verified."]
                    remember_claim(context, message, "completed_checks")
                    context['unresolved_questions'] = []
                try:
                    # Savepoint independiente para conservar mensajes si la validación del diagnóstico falla.
                    with transaction.atomic():
                        diagnostic = run_diagnostic(internet_service=session.internet_service, conversation=conversation)
                        automatic = diagnostic.result_code in {"SIGNAL_DEGRADED", "PERFORMANCE_DEGRADED"}
                        if automatic or intent in {Intent.REQUEST_TECHNICIAN, Intent.CONFIRM_PHYSICAL_CHECK}:
                            ticket = escalate_diagnostic(run=diagnostic, user=session.operator, reported_actions=reported_actions)
                    response_text = reply(diagnostic.result_code, selected_language)
                    requires_action = diagnostic.assessment["follow_up"]
                    if ticket:
                        if reported_actions and diagnostic.result_code == "CPE_UNREACHABLE":
                            display_key = "CPE_ESCALATED"
                            response_text = reply(display_key, selected_language)
                        response_text += " " + reply("ticket_created", selected_language, number=ticket.number)
                        requires_action = "WAIT_FOR_TECHNICAL_REVIEW"
                    # La presentación conserva lo ya explicado, sin alterar la política de diagnóstico.
                    if not reported_actions and context['reported_issue'] and diagnostic.result_code == 'CPE_UNREACHABLE':
                        display_key = 'CPE_FOLLOW_UP'
                        existing_ticket = ticket or conversation.tickets.exclude(status__in=['CLOSED', 'RESOLVED']).order_by('-created_at').first()
                        if existing_ticket:
                            ticket = existing_ticket
                            response_text = contextual_reply('PERSISTING_ISSUE', {**context, 'ticket': {'number': ticket.number, 'status': ticket.status}}, selected_language)
                            requires_action = 'WAIT_FOR_TECHNICAL_REVIEW'
                        else:
                            response_text = contextual_reply('PERSISTING_ISSUE', context, selected_language)
                except ValidationError as error:
                    logger.warning("Chat diagnostic failure conversation=%s category=%s", conversation.pk, type(error).__name__)
                    diagnostic, ticket = None, None
                    response_text = reply("diagnostic_unavailable", selected_language)
                    requires_action = "CONTACT_DEMO_OPERATOR"
        user_message.metadata = {"intent": intent.value, "reported_actions": reported_actions}
        user_message.save(update_fields=["metadata"])
        if intent in {Intent.NO_INTERNET, Intent.SLOW_INTERNET}:
            context['reported_issue'] = intent.value
        images = [] if display_key == 'CPE_ESCALATED' else relevant_images(diagnostic.result_code if diagnostic else None, selected_language)
        if intent == Intent.GUIDE_REQUEST:
            images = relevant_images((context.get('diagnostic') or {}).get('result_code'), selected_language)
        elif intent == Intent.EXPLAIN_POE:
            images = [item for item in catalog(selected_language) if item['id'] == f'poe-{selected_language}']
        elif intent == Intent.EQUIPMENT_CLARIFICATION and 'router' in message.lower():
            images = [item for item in catalog(selected_language) if item['id'] == f'router-{selected_language}']
        if intent not in {Intent.GUIDE_REQUEST, Intent.EXPLAIN_POE}:
            images = [image for image in images if image['id'] not in context['shown_guides']]
            if context.get('ticket') and diagnostic:
                images = []
        context['shown_guides'] = list(dict.fromkeys(context['shown_guides'] + [image['id'] for image in images]))[-20:]
        context['language'] = selected_language
        if diagnostic:
            context['diagnostic'] = {'id': diagnostic.pk, 'result_code': diagnostic.result_code, 'source': diagnostic.source}
        if ticket:
            context['ticket'] = {'number': ticket.number, 'status': ticket.status}
        Message.objects.create(
            conversation=conversation, sender=Message.Sender.ASSISTANT, content=response_text,
            metadata={"intent": intent.value, "provider_status": provider_status, "requires_action": requires_action,
                      "image_ids": [image["id"] for image in images],
                      "display_key": display_key,
                      "context": context,
                      "diagnostic_id": diagnostic.pk if diagnostic else None,
                      "ticket_id": str(ticket.pk) if ticket else None},
        )
        return {
            "conversation_id": conversation.pk, "message": response_text, "language": selected_language,
            "intent": intent.value, "diagnostic": diagnostic_payload(diagnostic, selected_language, display_key) if diagnostic else None,
            "ticket": {"id": str(ticket.pk), "number": ticket.number, "status": ticket.status} if ticket else None,
            "requires_action": requires_action, "provider_status": provider_status,
            "images": images,
        }
