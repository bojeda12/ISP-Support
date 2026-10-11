"""Orquestador: clasificar fuera de la transacción y ejecutar solo políticas explícitas."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, DatabaseError
from django.utils import timezone
from pydantic import ValidationError as SchemaValidationError

from diagnostics.services import escalate_diagnostic, run_diagnostic
from .ai import ConversationalReply, Interpretation, Intent, ProviderError, detect_language, get_provider
from .demo_sessions import demo_enabled, is_demo_service, operator_allowed
from .models import Conversation, Message
from .replies import diagnostic_payload, reply
from .instructions import relevant_images
from .instructions import catalog
from .context import conversation_context, contextual_reply, remember_claim, remember_answer, remember_equipment
from .short_answers import short_interpretation, short_answer
from .adaptive import guard_interpretation, evidence_state, authorized_recheck, adaptive_reply, factual_summary, uncertain_statement, review_eligibility, validate_ticket_claim
from .adaptive import progress_state, review_trace
from .adaptive import validate_tool_reply
from .decisions import Action, select_decision
from .operation_explanations import operation_outcome, explain_operation, validate_operation_claims
from .adaptive import DiagnosticRateLimit

logger = logging.getLogger(__name__)
trace_logger = logging.getLogger('conversations.runtime')
GENERATED_INTENTS = {Intent.PHOTO_QUESTION, Intent.PHOTO_COMPARISON,
    Intent.REPORT_INDICATORS, Intent.EQUIPMENT_CLARIFICATION, Intent.ANSWER_CLARIFICATION,Intent.EXPLAIN_POE,Intent.CLARIFY_COMPLETED_CHECKS,Intent.OTHER}


def bounded_history(conversation, before_message_id: int) -> list[dict]:
    messages = conversation.messages.filter(pk__lt=before_message_id).order_by("-created_at", "-pk")[:min(4, settings.CHAT_HISTORY_MESSAGES)]
    history, remaining = [], min(2000, settings.CHAT_HISTORY_CHARACTERS)
    for message in messages:
        if message.sender not in {Message.Sender.CUSTOMER, Message.Sender.ASSISTANT}:
            continue
        if message.metadata.get('type') == 'photo_analysis':
            continue
        from knowledge.services import historical_customer_text
        content = historical_customer_text(message)[:min(1000, remaining)]
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


def chat(*, session, message: str, conversation=None, language=None, initial_language=None, upload=None, stored_keys=None, customer_response=None) -> dict:
    ensure_session(session)
    message = message.strip()
    image_only = not message and upload is not None
    if image_only:
        message = 'Photo uploaded.' if (language or initial_language or getattr(conversation,'language','en')) == 'en' else 'Fotografía enviada.'
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
            conversation=conversation, sender=Message.Sender.CUSTOMER, content=message,
            metadata={'quick_reply': customer_response} if customer_response else {},
        )
    provider_status = "ok"
    if upload is not None:
        from .photos import upload_and_analyze
        conversation.language = selected_language
        upload_and_analyze(session=session,conversation=conversation,upload=upload,
            message=user_message,emit_reply=False,question='' if image_only else message,stored_keys=stored_keys)
    provider = None
    generated = None
    generated_question = 'none'
    generated_citations = []
    reply_failed = False
    classification_attempted = False
    reply_attempted = False
    classification_succeeded = False
    reply_succeeded = False
    fallback_reason = None
    proposed_action = 'none'
    context = conversation_context(conversation)
    if customer_response:
        context['customer_response'] = customer_response
    try:
        history = bounded_history(conversation, user_message.pk)
        # Un resumen estructurado sustituye una entrada, manteniendo los límites existentes.
        history = [{"role": "context", "content": "", "context": context}] + history[:max(0, settings.CHAT_HISTORY_MESSAGES - 1)]
        provider = get_provider()
        raw = Interpretation(intent=Intent.PHOTO_QUESTION,language=selected_language) if image_only and settings.AI_PROVIDER != 'openai' else provider.interpret(
            message=message, history=history, language=selected_language
        )
        interpreted = Interpretation.model_validate(raw)
        classification_succeeded = True
        proposed_action = interpreted.next_action
        selected_language = language or interpreted.language
        if settings.AI_PROVIDER == 'demo':
            interpreted = short_interpretation(message, selected_language) or interpreted
        interpreted = guard_interpretation(interpreted, message, context)
        if image_only and settings.AI_PROVIDER == 'demo':
            from .adaptive import demo_proposal
            interpreted = demo_proposal(interpreted,context)
    except (ProviderError, SchemaValidationError, TimeoutError) as error:
        known_reasons = {"configuration_missing", "invalid_or_refused_output", "timeout", "upstream_error", "invalid_output", "unknown_provider"}
        reason = str(error) if isinstance(error, ProviderError) and str(error) in known_reasons else type(error).__name__
        logger.warning("Chat provider failure conversation=%s reason=%s", conversation.pk, reason)
        from .ai import DemoAIProvider
        fallback_interpretation = DemoAIProvider().interpret(message=message,history=[{'context':context}],language=selected_language)
        interpreted = fallback_interpretation
        if context.get('decision_contract'):
            from .decisions import Decision
            interpreted = interpreted.model_copy(update={'decision':Decision(action=Action.ANSWER_CUSTOMER,
                reason='Provider unavailable; evaluate preserved reports with existing server policy.')})
        interpreted = short_interpretation(message, selected_language) or interpreted
        interpreted = guard_interpretation(interpreted, message, context)
        fallback_reason = reason
        provider_status = "unavailable"

    classification_attempted = getattr(provider, 'external_call_attempted', False) is True
    # Respaldo limitado para una preferencia humana explícita: no concede permisos nuevos.
    from .ai import DemoAIProvider
    explicit_preference=DemoAIProvider().interpret(message=message,history=[{'context':context}],language=selected_language)
    if explicit_preference.support_preference == 'human':
        interpreted=interpreted.model_copy(update={'intent':Intent.REQUEST_TECHNICIAN,'support_preference':'human'})
    human_requested = interpreted.support_preference == 'human' or interpreted.intent == Intent.REQUEST_TECHNICIAN
    if interpreted.issue_category in {'NO_POWER','WIFI_ISSUE','INTERMITTENT_CONNECTION'} and not human_requested:
        interpreted = interpreted.model_copy(update={'intent':Intent.OTHER,'next_action':'none'})
    if session.internet_service.status != 'ACTIVE' and not human_requested:
        interpreted = interpreted.model_copy(update={'intent':Intent.CHECK_SERVICE_STATUS,'issue_category':'ADMIN_SUSPENDED','next_action':'none'})
    resume_requested = interpreted.support_preference == 'self_service'
    if resume_requested and (context.get('diagnostic') or {}).get('result_code') == 'SIGNAL_DEGRADED':
        context['signal_support_note'] = ('Customer voluntarily resumes safe troubleshooting: the latest simulated check shows reachable '
            'equipment with degraded signal, not proof of browsing. Ask whether access is completely unavailable, intermittent or slow. '
            'Keep the existing ticket and do not claim a new measurement or repeat a PoE guide.')
    active_handoff = context.get('workflow_state') == 'HANDOFF_PENDING' and context.get('ticket') and context['ticket']['status'] in {'OPEN','IN_PROGRESS'}
    volunteered_check = active_handoff and (interpreted.intent == Intent.CONFIRM_PHYSICAL_CHECK or interpreted.check_evidence == 'completed_report')
    if active_handoff and not resume_requested and interpreted.intent not in {Intent.EXPLAIN_POE,Intent.GUIDE_REQUEST,Intent.CHECK_TICKET}:
        interpreted = interpreted.model_copy(update={'intent':Intent.OTHER if interpreted.support_help_requested and not human_requested else Intent.CHECK_TICKET,'next_action':'none','question_kind':'none'})
    adaptive_run, adaptive_ticket = None, None
    tool_result = {'executed':False,'reason':'not_requested'}
    # Una vista adicional útil permite avanzar sin volver a pedir modelo/imagen.
    latest_photo = conversation.photos.order_by('-created_at','-pk').first()
    previous = conversation.diagnostic_runs.order_by('-created_at','-pk').first()
    useful_new_view = bool(upload is not None and latest_photo and latest_photo.status == 'COMPLETED' and previous and latest_photo.created_at > previous.created_at and len(context.get('photos',[])) >= 2 and context.get('reported_issue') == 'NO_INTERNET')
    current_evidence = {**context,**evidence_state(context,interpreted,message,user_message.pk)}
    progress = progress_state(current_evidence,interpreted,message,user_message.pk)
    model_decision, authorized_decision = select_decision(interpreted, {**current_evidence,**progress}, previous,
        policy_enabled=settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW)
    decision_recheck = bool(previous and authorized_decision.action in {Action.RUN_AUTHORIZED_RECHECK,Action.REQUEST_TECHNICAL_REVIEW}
        and interpreted.decision is not None and session.internet_service.status == 'ACTIVE' and not human_requested
        and interpreted.intent != Intent.CONFIRM_PHYSICAL_CHECK)
    if decision_recheck:
        interpreted = interpreted.model_copy(update={'intent':Intent.PHOTO_QUESTION,
            'next_action':'recheck','question_kind':'none'})
    stale_decision_result = bool(decision_recheck and (not previous.completed_at or
        previous.completed_at < timezone.now()-timedelta(seconds=settings.CHAT_REVIEW_DIAGNOSTIC_MAX_AGE_SECONDS)))
    progress_recheck = bool(settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW and previous
        and interpreted.issue_category in {'unknown','NO_INTERNET'}
        and not context.get('ticket') and progress['diminishing_customer_checks']
        and conversation.diagnostic_runs.count() < 2)
    unavailable_checks = bool(settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW and previous and interpreted.additional_checks == 'unavailable' and context.get('additional_checks') != 'unavailable' and any(item.get('attempted') or item.get('status') == 'customer_reported_complete' for item in current_evidence['customer_reported_checks']))
    if provider_status == 'ok' and unavailable_checks and interpreted.intent in GENERATED_INTENTS:
        interpreted = interpreted.model_copy(update={'next_action':'recheck','question_kind':'none'})
    if provider_status == 'ok' and not active_handoff and (progress_recheck or useful_new_view and interpreted.check_evidence != 'attempted_uncertain'):
        # La incertidumbre visual no impide medir de nuevo por la herramienta autorizada.
        if interpreted.intent not in GENERATED_INTENTS:
            interpreted = interpreted.model_copy(update={'intent':Intent.PHOTO_QUESTION})
        interpreted = interpreted.model_copy(update={'next_action':'recheck','question_kind':'none'})
    if (provider_status == 'ok' or decision_recheck) and interpreted.next_action in {'recheck','recommend_escalation'} and interpreted.intent in GENERATED_INTENTS:
        if (interpreted.check_evidence == 'attempted_uncertain' or uncertain_statement(message)) and not (unavailable_checks or progress_recheck or decision_recheck):
            tool_result = {'executed':False,'reason':'uncertain_checks'}
        else:
            previous = conversation.diagnostic_runs.order_by('-created_at','-pk').first()
            latest_photo = conversation.photos.order_by('-created_at').first()
            new_photo = bool(latest_photo and latest_photo.status == 'COMPLETED' and (previous is None or latest_photo.created_at > previous.created_at))
            try:
                adaptive_run, tool_result = authorized_recheck(session=session,conversation=conversation,message=message,
                    new_photo=new_photo,completed=interpreted.check_evidence == 'completed_report',
                    new_issue=unavailable_checks or progress_recheck or stale_decision_result or decision_recheck and conversation.diagnostic_runs.count() < 2,
                    explicit_request=interpreted.intent == Intent.REQUEST_TECHNICIAN)
            except ValidationError:
                tool_result = {'executed':False,'reason':'simulation_unavailable'}
            context = conversation_context(conversation)
            eligible_evidence = {**context,**evidence_state(context,interpreted,message,user_message.pk)}
            if interpreted.next_action == 'recommend_escalation' and eligible_evidence['confirmed_completed_checks'] and adaptive_run:
                adaptive_ticket = escalate_diagnostic(run=adaptive_run,user=session.operator,reported_actions=factual_summary(eligible_evidence))
                context = conversation_context(conversation)
            elif review_eligibility(conversation,eligible_evidence,adaptive_run):
                adaptive_ticket = escalate_diagnostic(run=adaptive_run,user=session.operator,
                    reported_actions=factual_summary(eligible_evidence) + ['Technical-review eligibility: persistent outage after guided attempts and review of available evidence; further checks are inconclusive or unavailable; physical checks remain unverified.'])
                context = conversation_context(conversation)
    if (provider_status == 'ok' or decision_recheck) and adaptive_ticket is None and not active_handoff and settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW:
        eligible_evidence = {**context,**evidence_state(context,interpreted,message,user_message.pk)}
        latest_run = adaptive_run or conversation.diagnostic_runs.order_by('-created_at','-pk').first()
        if review_eligibility(conversation,eligible_evidence,latest_run):
            ensure_session(session)
            adaptive_ticket = escalate_diagnostic(run=latest_run,user=session.operator,
                reported_actions=factual_summary(eligible_evidence) + ['Technical-review eligibility: persistent outage after guided attempts and review of available evidence; further checks are inconclusive or unavailable; physical checks remain unverified.'])
            adaptive_run = latest_run
            context = conversation_context(conversation)
    # Solo texto; acciones bajo control Django. El endpoint multipart conserva una
    # transacción exterior para confirmar o revertir el turno completo.
    generation_context = context
    from knowledge.services import retrieve, validate_citations, citation_text, tokens, public_citations, validate_customer_answer
    retrieval_error = None
    retrieval_message = message
    if short_interpretation(message, selected_language):
        retrieval_message += {Intent.PHOTO_QUESTION:' Ethernet connectors link lights', Intent.REPORT_INDICATORS:' LED power indicator lights',Intent.EQUIPMENT_CLARIFICATION:' router modem gateway PoE injector equipment identification'}.get(interpreted.intent,'')
    try:
        knowledge = retrieve(customer_id=conversation.customer_id,message=message,query_text=retrieval_message,context=context,language=selected_language)
    except Exception:
        # No imprimir excepciones: podrían contener texto documental o datos del SDK.
        retrieval_error = 'retrieval_error'
        knowledge = {'sources':[], 'specific_available':False, 'equipment_model':None,'conflict':False,'source_mismatch':False}
    shared_sources = [source for source in knowledge['sources'] if source['external_allowed']]
    from knowledge.cases import retrieve_cases, record_usage
    from knowledge.strategies import investigation_strategy
    issue_category=interpreted.issue_category if interpreted.issue_category != 'unknown' else context.get('issue_category','unknown')
    if issue_category=='unknown':
        issue_category=context.get('reported_issue','unknown')
    strategy=investigation_strategy(issue_category,selected_language)
    remaining=[]
    if strategy:
        known=set(current_evidence.get('supplied_evidence',[]))
        if context.get('diagnostic'):
            known.add('cpe_reachability')
        remaining=[item for item in strategy['relevant_evidence'] if item not in known]
    try:
        similar_cases=retrieve_cases(customer=conversation.customer,context={**context,'issue_category':issue_category},message=message,language=selected_language)
    except Exception:
        similar_cases=[]
        retrieval_error=retrieval_error or 'case_retrieval_error'
    reply_context = {**context,**evidence_state(context, interpreted, message, user_message.pk),'tool_result':tool_result,
        'operation_outcome':operation_outcome(adaptive_run,tool_result,adaptive_ticket or context.get('ticket'),user_message),
        'reported_checks_this_turn':interpreted.checks_attempted or interpreted.intent == Intent.CONFIRM_PHYSICAL_CHECK,
        'accepted_next_action':interpreted.next_action,'knowledge':shared_sources,
        'knowledge_state':{'specific_available':knowledge['specific_available'] and bool(shared_sources), 'conflict':knowledge['conflict']}}
    reply_context.update(progress_state(reply_context,interpreted,message,user_message.pk))
    if adaptive_ticket:
        authorized_decision = authorized_decision.model_copy(update={'action':Action.REQUEST_TECHNICAL_REVIEW,
            'reason':'Existing technical-review predicates satisfied by actual measurements and reported evidence.'})
    elif adaptive_run and adaptive_run.result_code == 'NO_FAULT_DETECTED':
        authorized_decision = authorized_decision.model_copy(update={'action':Action.VERIFY_CUSTOMER_CONNECTIVITY,
            'reason':'Healthy simulated result; customer restoration still requires confirmation.'})
    reply_context['authorized_decision'] = authorized_decision.model_dump(mode='json')
    controlled_decision = interpreted.decision is not None or decision_recheck
    reply_context.update(investigation_strategy=strategy,
        remaining_useful_checks=remaining,
        historical_cases=[item['pattern'] for item in similar_cases if item['external_allowed']])
    if provider_status == 'ok' and settings.AI_PROVIDER == 'openai' and interpreted.intent in GENERATED_INTENTS:
        try:
            provider.external_call_attempted = False
            generated_reply = ConversationalReply.model_validate(provider.generate_reply(
                message=message, context=reply_context, language=selected_language,
                intent=interpreted.intent.value, focus=interpreted.photo_focus))
            answered_kinds = {item['question'] for item in reply_context['answered_questions']}
            blocked = answered_kinds | ({'equipment_model'} if context.get('reported_issue') else set())
            if interpreted.decision is not None or decision_recheck:
                if authorized_decision.action != Action.REQUEST_NECESSARY_EVIDENCE:
                    blocked |= {'front_photo','other_photo','indicator_label','completed_checks'}
                else:
                    blocked |= {'front_photo','other_photo','indicator_label','completed_checks','power','cable_path','physical_access'} - {authorized_decision.required_fact}
            if not settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW:
                blocked.discard('completed_checks')
            if settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW and progress['diminishing_customer_checks']:
                blocked |= {'front_photo','other_photo','indicator_label','completed_checks'}
            if active_handoff:
                blocked |= {'equipment_model','front_photo','other_photo','indicator_label','completed_checks'}
            forbidden_question = controlled_decision and authorized_decision.action not in {Action.REQUEST_NECESSARY_EVIDENCE,Action.VERIFY_CUSTOMER_CONNECTIVITY}
            if generated_reply.question_kind in blocked or forbidden_question and '?' in generated_reply.answer:
                # Una única reparación del modelo conserva razonamiento natural; no oculta fallos.
                generated_reply = ConversationalReply.model_validate(provider.generate_reply(
                    message=message, context={**reply_context,'blocked_question_kinds':sorted(blocked),
                        'response_correction':'Answer using existing evidence and actual tool results; omit already answered questions.'},
                    language=selected_language,intent=interpreted.intent.value,focus=interpreted.photo_focus))
                if generated_reply.question_kind in blocked or forbidden_question and '?' in generated_reply.answer:
                    raise ProviderError('redundant_evidence_request')
            generated = generated_reply.answer
            validate_customer_answer(generated,knowledge['sources'])
            validate_ticket_claim(generated,context.get('ticket'))
            validate_operation_claims(generated,reply_context['operation_outcome'])
            if controlled_decision:
                validate_tool_reply(generated,tool_result,context.get('ticket'))
            if (adaptive_ticket and generated_reply.question_kind != 'none') or (generated_reply.question_kind in {'equipment_model','front_photo','other_photo'} and useful_new_view) or (generated_reply.question_kind == 'equipment_model' and context.get('equipment_claim') and interpreted.photo_focus != 'indicators'):
                raise ProviderError('redundant_evidence_request')
            generated_question = generated_reply.question_kind
            generated_citations = validate_citations(generated_reply.citations,shared_sources)
            if not generated_citations and any(term in generated.lower() for term in ('according to the manual','consulted the manual','según el manual','consulté el manual')):
                raise ProviderError('unverified_manual_claim')
            reply_succeeded = True
        except (ProviderError, SchemaValidationError, TimeoutError) as error:
            generated = None
            reply_failed = True
            provider_status = 'reply_unavailable'
            fallback_reason = safe_failure_reason(error)
        finally:
            reply_attempted = getattr(provider, 'external_call_attempted', False) is True

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        context = conversation_context(conversation)
        context_unchanged = context == generation_context
        context.update(evidence_state(context, interpreted, message, user_message.pk))
        context.update(progress_state(context, interpreted, message, user_message.pk))
        context['decision_contract'] = context.get('decision_contract',False) or interpreted.decision is not None
        if human_requested:
            context['support_preference']='human'
        if resume_requested:
            context['support_preference']='self_service'
            context['workflow_state']='SELF_SERVICE'
        if interpreted.issue_category != 'unknown':
            context['issue_category']=interpreted.issue_category
        context['next_recommended_action'] = interpreted.next_action
        conversation.language = selected_language
        conversation.save(update_fields=["language", "updated_at"])
        intent = interpreted.intent
        response_text = reply("other", selected_language)
        requires_action, diagnostic, ticket = "DESCRIBE_PROBLEM", adaptive_run, adaptive_ticket
        reported_actions = []
        display_key = None
        contextual = {Intent.EQUIPMENT_CLARIFICATION, Intent.REPORT_INDICATORS,
            Intent.CLARIFY_COMPLETED_CHECKS, Intent.EXPLAIN_POE, Intent.REQUEST_PHOTO,
            Intent.PHOTO_QUESTION, Intent.PHOTO_COMPARISON, Intent.ANSWER_CLARIFICATION}
        response_source = 'django_template'
        fallback_used = reply_failed or provider_status == 'unavailable' or retrieval_error is not None
        fallback_reason = fallback_reason or retrieval_error
        if provider_status == "unavailable" and not adaptive_run and not human_requested and not short_interpretation(message, selected_language) and interpreted.check_evidence not in {'attempted_uncertain','completed_report'}:
            response_text = reply("unavailable", selected_language)
            requires_action = "RETRY_MESSAGE"
            response_source = 'provider_error'
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
            if volunteered_check and ticket:
                from tickets.services import record_ticket_action
                record_ticket_action(ticket=ticket,user=session.operator,
                    description='Customer-reported actions (not verified): ' + message[:300])
            response_text = reply("ticket_status", selected_language, number=ticket.number, status=ticket.status) if ticket else reply("no_ticket", selected_language)
            requires_action = "NONE"
        elif intent in contextual or (intent == Intent.OTHER and context['reported_issue']):
            if intent in {Intent.EQUIPMENT_CLARIFICATION, Intent.REPORT_INDICATORS, Intent.CLARIFY_COMPLETED_CHECKS}:
                remember_claim(context, message, intent.value)
            if intent == Intent.EQUIPMENT_CLARIFICATION:
                remember_equipment(context, message)
            if intent == Intent.ANSWER_CLARIFICATION:
                remember_answer(context, message)
            response_text = contextual_reply(intent.value, {**context,'current_supplied_evidence':interpreted.supplied_evidence}, selected_language, interpreted.photo_focus)
            response_text = short_answer(message, context, selected_language, intent) or response_text
            if (interpreted.check_evidence == 'attempted_uncertain' or interpreted.next_action == 'request_photo' and interpreted.question_kind == 'front_photo') and not adaptive_run and intent not in {Intent.EXPLAIN_POE,Intent.EQUIPMENT_CLARIFICATION}:
                response_text = adaptive_reply(context,selected_language,interpreted.next_action == 'request_photo')
            elif adaptive_run:
                response_text = reply(adaptive_run.result_code,selected_language)
                if not tool_result['executed']:
                    response_text = contextual_reply('PERSISTING_ISSUE',context,selected_language)
                elif adaptive_run.result_code == 'CPE_UNREACHABLE':
                    response_text = ('The new simulated check still cannot reach the outdoor CPE. The photo cannot confirm Internet connectivity or the cause. Which accessible checks can you confirm you completed?' if selected_language == 'en' else
                        'La nueva comprobación simulada todavía no alcanza el CPE exterior. La fotografía no confirma conectividad a Internet ni la causa. ¿Qué comprobaciones accesibles puedes confirmar que completaste?')
                if adaptive_ticket:
                    response_text = ('The simulated network check still cannot reach your outdoor equipment. Your troubleshooting attempts provide enough information for technical review; further uncertain checks are not required now.' if selected_language == 'en' else
                        'La comprobación de red simulada sigue sin alcanzar tu equipo exterior. Tus intentos de comprobación aportan información suficiente para revisión técnica; no necesitas repetir comprobaciones inciertas ahora.') + ' ' + reply('ticket_created',selected_language,number=adaptive_ticket.number)
            response_source = 'demo_template' if settings.AI_PROVIDER == 'demo' else 'django_context_template'
            if generated is not None and context_unchanged:
                response_text = generated
                response_source = 'openai_generated'
            elif generated is not None:
                # Un turno concurrente cambió el estado: no publicar una respuesta obsoleta.
                fallback_used = True
                response_source = 'context_changed_fallback'
                fallback_reason = 'context_changed'
            if reply_failed or provider_status == 'unavailable':
                notice = ('I can give limited guidance based on the information currently available.'
                    if selected_language == 'en' else 'Puedo orientarte de forma limitada con la información disponible.')
                response_text = notice + ' ' + response_text
                response_source = 'reply_error_fallback' if reply_failed else 'provider_error'
            requires_action = "CLARIFY_CONTEXT"
            if adaptive_ticket:
                requires_action = 'WAIT_FOR_TECHNICAL_REVIEW'
            pending = {Intent.EQUIPMENT_CLARIFICATION: 'equipment_model',
                       Intent.REPORT_INDICATORS: 'indicator_label',
                       Intent.CLARIFY_COMPLETED_CHECKS: 'completed_checks'}
            answered = {v['question'] for v in context['answered_questions']}
            if intent in pending and pending[intent] not in answered:
                context['unresolved_questions'] = [pending[intent]]
            if adaptive_ticket or adaptive_run and tool_result['executed']:
                context['unresolved_questions'] = []
            if response_source == 'openai_generated' and generated_question != 'none' and generated_question not in answered:
                context['unresolved_questions'] = [generated_question]
            if interpreted.question_kind != 'none' and interpreted.question_kind not in answered and interpreted.next_action in {'ask_question','request_photo'} and not adaptive_ticket:
                context['unresolved_questions'] = [interpreted.question_kind]
            if intent in {Intent.PHOTO_QUESTION, Intent.PHOTO_COMPARISON} and context['photo']:
                context['discussed_photo_ids'] = list(dict.fromkeys(context['discussed_photo_ids'] + [context['photo']['id']]))[-6:]
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
                        unsupported_issue=interpreted.issue_category in {'NO_POWER','WIFI_ISSUE','INTERMITTENT_CONNECTION'}
                        if unsupported_issue and previous is None:
                            raise ValidationError('No implemented diagnostic capability for this issue.')
                        diagnostic, tool_result = authorized_recheck(session=session,conversation=conversation,message=message,
                            completed=intent == Intent.CONFIRM_PHYSICAL_CHECK, explicit_request=intent == Intent.REQUEST_TECHNICIAN and not unsupported_issue,
                            new_issue=intent == Intent.SLOW_INTERNET and context['reported_issue'] != 'SLOW_INTERNET')
                        if intent == Intent.CONFIRM_PHYSICAL_CHECK and not tool_result['executed'] and not tool_result.get('fresh',False):
                            tool_result={**tool_result,'reason':'stale_result_rate_limited'}
                            raise ValidationError('No fresh authorized diagnostic result is available.')
                        automatic = diagnostic.result_code in {"SIGNAL_DEGRADED", "PERFORMANCE_DEGRADED"}
                        if automatic or intent in {Intent.REQUEST_TECHNICIAN, Intent.CONFIRM_PHYSICAL_CHECK}:
                            ticket = escalate_diagnostic(run=diagnostic, user=session.operator, reported_actions=list(dict.fromkeys(reported_actions + factual_summary(context))))
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
                except DiagnosticRateLimit as error:
                    diagnostic, ticket = None, None
                    tool_result={'executed':False,'reason':'frequency_limit','retry_after_seconds':error.retry_after}
                    response_text = (f'The simulated connection-check limit for this service has been reached. No new measurement was taken. Your conversation is saved; try again in {error.retry_after} seconds.' if selected_language == 'en' else
                        f'Se alcanzó el límite de comprobaciones simuladas de este servicio. No se realizó una medición nueva. Tu conversación está guardada; vuelve a intentarlo en {error.retry_after} segundos.')
                    requires_action='WAIT_DIAGNOSTIC_LIMIT'
                except (ValidationError, DatabaseError) as error:
                    logger.exception("Chat diagnostic failure conversation=%s category=%s", conversation.pk, type(error).__name__)
                    diagnostic, ticket = None, None
                    if tool_result['reason'] != 'stale_result_rate_limited':
                        tool_result={'executed':False,'reason':'operation_unavailable'}
                    response_text = reply("diagnostic_unavailable", selected_language)
                    requires_action = "CONTACT_DEMO_OPERATOR"
        user_message.metadata = {**user_message.metadata,"intent": intent.value, "reported_actions": reported_actions}
        if strategy and intent == Intent.OTHER and interpreted.issue_category in {'NO_POWER','WIFI_ISSUE','INTERMITTENT_CONNECTION'} and response_source != 'openai_generated':
            checks=strategy['safe_checks']
            response_text=(' '.join(checks[:2]) + (' Specialized measurements for this issue are unavailable in this demo.' if selected_language == 'en' else ' Las mediciones especializadas de este problema no están disponibles en esta demo.'))
            requires_action='REVIEW_SAFE_CHECKS'
        if human_requested and ticket is None and not (context.get('ticket') and context['ticket']['status'] in {'OPEN','IN_PROGRESS'}):
            response_text += (' I could not confirm a support ticket under the current policy. Please contact the authorized demo operator for assistance.' if selected_language == 'en' else
                ' No pude confirmar un ticket de soporte con la política actual. Contacta al operador autorizado de la demo para recibir asistencia.')
            requires_action='CONTACT_ADMINISTRATION' if session.internet_service.status != 'ACTIVE' else 'CONTACT_DEMO_OPERATOR'
        # Una propuesta operacional nueva se explica después de ejecutar/reutilizar la
        # herramienta. Compatibilidad con interpretaciones antiguas sin next_action.
        if ticket and intent == Intent.CONFIRM_PHYSICAL_CHECK:
            authorized_decision=authorized_decision.model_copy(update={'action':Action.REQUEST_TECHNICAL_REVIEW,
                'reason':'Existing confirmed-check escalation policy executed after the authorized result.'})
        if diagnostic and intent not in GENERATED_INTENTS and (interpreted.next_action != 'none' or interpreted.decision is not None) and settings.AI_PROVIDER == 'openai' and provider_status == 'ok':
            try:
                provider.external_call_attempted = False
                if ticket:
                    authorized_decision=authorized_decision.model_copy(update={'action':Action.REQUEST_TECHNICAL_REVIEW,
                        'reason':'Existing confirmed-check escalation policy executed after the authorized result.'})
                after_context = {**context,'diagnostic':{'id':diagnostic.pk,'result_code':diagnostic.result_code,'source':diagnostic.source},
                    'operation_outcome':operation_outcome(diagnostic,tool_result,ticket,user_message),
                    'reported_checks_this_turn':interpreted.checks_attempted or intent == Intent.CONFIRM_PHYSICAL_CHECK,
                    'tool_result':tool_result,'knowledge':shared_sources,
                    'ticket':{'number':ticket.number,'status':ticket.status} if ticket else context.get('ticket')}
                after_context['latest_diagnostic'] = after_context['diagnostic']
                after_context['active_ticket'] = after_context['ticket']
                if diagnostic.result_code == 'SIGNAL_DEGRADED':
                    after_context['signal_support_note'] = (
                        'The equipment is reachable with degraded simulated signal. A NO_INTERNET report is a customer symptom, '
                        'not a CPE_UNREACHABLE measurement. Explain this distinction. An OPEN ticket does not confirm assignment '
                        'or active technician review. Ticket creation here follows measured link degradation, not completed '
                        'customer checks. Offer optional continued safe troubleshooting to clarify total loss, intermittent '
                        'access or slow Internet; never impose a PoE guide or claim successful browsing. '
                        'If support_preference=self_service, ask one concise question distinguishing these symptoms.')
                if human_requested and ticket:
                    after_context['workflow_state']='HANDOFF_PENDING'
                after_context['investigation_strategy']=strategy
                after_context['historical_cases']=[item['pattern'] for item in similar_cases if item['external_allowed']]
                after_context['authorized_decision']=authorized_decision.model_dump(mode='json')
                final_reply = ConversationalReply.model_validate(provider.generate_reply(message=message,context=after_context,language=selected_language,intent=intent.value,focus=interpreted.photo_focus))
                forbidden_question = controlled_decision and authorized_decision.action not in {Action.REQUEST_NECESSARY_EVIDENCE,Action.VERIFY_CUSTOMER_CONNECTIVITY}
                if final_reply.question_kind == 'equipment_model' or human_requested and ticket and final_reply.question_kind != 'none' or forbidden_question and '?' in final_reply.answer:
                    final_reply = ConversationalReply.model_validate(provider.generate_reply(
                        message=message,context={**after_context,'blocked_question_kinds':['equipment_model','front_photo','other_photo','indicator_label','completed_checks'] if human_requested and ticket else ['equipment_model'],
                            'response_correction':'Do not request unnecessary information or restart an accepted human handoff. Use the actual diagnostic and ticket result.'},
                        language=selected_language,intent=intent.value,focus=interpreted.photo_focus))
                    if final_reply.question_kind == 'equipment_model' or human_requested and ticket and final_reply.question_kind != 'none' or forbidden_question and '?' in final_reply.answer:
                        raise ProviderError('redundant_evidence_request')
                generated_citations = validate_citations(final_reply.citations,shared_sources)
                validate_customer_answer(final_reply.answer,knowledge['sources'])
                validate_ticket_claim(final_reply.answer,after_context['ticket'])
                validate_operation_claims(final_reply.answer,after_context['operation_outcome'])
                if controlled_decision:
                    validate_tool_reply(final_reply.answer,tool_result,after_context['ticket'])
                if not generated_citations and any(term in final_reply.answer.lower() for term in ('according to the manual','consulted the manual','según el manual','consulté el manual')):
                    raise ProviderError('unverified_manual_claim')
                reply_succeeded = True
                response_text = final_reply.answer
                response_source = 'openai_generated'
                if final_reply.question_kind != 'none' and final_reply.question_kind not in context['unresolved_questions']:
                    context['unresolved_questions'].append(final_reply.question_kind)
            except (ProviderError,SchemaValidationError,TimeoutError) as error:
                fallback_used = True
                fallback_reason = safe_failure_reason(error)
            finally:
                reply_attempted = getattr(provider,'external_call_attempted',False) is True
        user_message.save(update_fields=["metadata"])
        if diagnostic and not tool_result['executed'] and response_source != 'openai_generated':
            response_text = response_text.replace('The new simulated diagnostic','The latest available simulated diagnostic').replace('El nuevo diagnóstico simulado','El último diagnóstico simulado disponible')
        citations = generated_citations if response_source == 'openai_generated' else []
        if intent in GENERATED_INTENTS:
            local_citation = (response_source != 'openai_generated' or not shared_sources) and bool(knowledge['sources'])
            if local_citation:
                source = knowledge['sources'][0]
                lines = [line for line in source['excerpt'].splitlines() if len(line.strip()) > 40]
                line = max(lines,key=lambda text:len(tokens(message)&tokens(text)),default=source['excerpt'][:300])
                citations = [{key:source[key] for key in ['section_id','document_id','title','revision','page','heading','generic']} | {'quote':line[:350]}]
        displayed_citations = public_citations(citations,knowledge['sources'])
        if displayed_citations:
            response_text += ' ' + citation_text(displayed_citations,selected_language)
        if intent in {Intent.NO_INTERNET, Intent.SLOW_INTERNET}:
            context['reported_issue'] = intent.value
        images = [] if display_key == 'CPE_ESCALATED' else relevant_images(diagnostic.result_code if diagnostic else None, selected_language)
        equipment_text = (context.get('equipment_claim') or {}).get('text','').lower()
        if diagnostic and diagnostic.result_code == 'CPE_UNREACHABLE' and (context['completed_checks'] or (any(term in equipment_text for term in ('frontier','modem','gateway','fiber','dsl')) and 'poe' not in equipment_text)):
            images = []
        if intent == Intent.GUIDE_REQUEST:
            images = relevant_images((context.get('diagnostic') or {}).get('result_code'), selected_language)
        elif intent == Intent.EXPLAIN_POE:
            images = [item for item in catalog(selected_language) if item['id'] == f'poe-{selected_language}']
        elif intent == Intent.EQUIPMENT_CLARIFICATION and 'router' in message.lower():
            images = [item for item in catalog(selected_language) if item['id'] == f'router-{selected_language}']
        if intent not in {Intent.GUIDE_REQUEST, Intent.EXPLAIN_POE}:
            shown_topics = {image_id.rsplit('-', 1)[0] for image_id in context['shown_guides']}
            images = [image for image in images if image['id'].rsplit('-', 1)[0] not in shown_topics]
            if context.get('ticket') and diagnostic:
                images = []
        context['shown_guides'] = list(dict.fromkeys(context['shown_guides'] + [image['id'] for image in images]))[-20:]
        context['language'] = selected_language
        context['troubleshooting_stage'] = 'technical_review' if ticket or context.get('ticket') else 'clarify_evidence' if interpreted.check_evidence == 'attempted_uncertain' else 'rechecked' if tool_result['executed'] else 'collect_evidence' if context['reported_issue'] else 'identify_issue'
        context['pending_questions'] = context['unresolved_questions']
        if diagnostic:
            context['diagnostic'] = {'id': diagnostic.pk, 'result_code': diagnostic.result_code, 'source': diagnostic.source}
        if ticket:
            context['ticket'] = {'number': ticket.number, 'status': ticket.status}
            context['next_recommended_action'] = 'technical_review'
        if context.get('support_preference') == 'human' and context.get('ticket') and context['ticket']['status'] in {'OPEN','IN_PROGRESS'}:
            context['workflow_state']='HANDOFF_PENDING'
            context['unresolved_questions']=[]
            context['pending_questions']=[]
        if resume_requested and not ticket and (context.get('diagnostic') or {}).get('result_code') == 'SIGNAL_DEGRADED' and context.get('ticket'):
            ticket = conversation.tickets.filter(number=context['ticket']['number'],
                customer=conversation.customer,internet_service=conversation.internet_service,
                status__in=['OPEN','IN_PROGRESS']).first()
        outcome = operation_outcome(diagnostic,tool_result,ticket,user_message)
        explanation_context = {**context, 'operation_outcome':outcome,
            'completed_report_this_turn':intent == Intent.CONFIRM_PHYSICAL_CHECK or interpreted.check_evidence == 'completed_report',
            'reported_checks_this_turn':interpreted.checks_attempted or intent == Intent.CONFIRM_PHYSICAL_CHECK}
        if controlled_decision and response_source != 'openai_generated' and (intent in GENERATED_INTENTS or intent == Intent.CONFIRM_PHYSICAL_CHECK):
            from .decisions import fallback_answer
            response_text = fallback_answer({**explanation_context,'tool_result':tool_result}, selected_language, authorized_decision, diagnostic, ticket)
        if response_source != 'openai_generated' and intent == Intent.CONFIRM_PHYSICAL_CHECK:
            response_text = explain_operation(explanation_context, selected_language)
        if resume_requested and (context.get('diagnostic') or {}).get('result_code') == 'SIGNAL_DEGRADED' and response_source != 'openai_generated':
            active = ticket or context.get('ticket')
            number = active.number if ticket else active['number'] if active else ''
            status = active.status if ticket else active['status'] if active else ''
            response_text = ('The latest available simulated check shows reachable equipment with degraded signal. This does not confirm you can browse. '
                'Is Internet completely unavailable, intermittent, or slow?' if selected_language == 'en' else
                'La última comprobación simulada disponible muestra que el equipo responde, pero la señal está degradada. Eso no confirma que puedas navegar. '
                '¿No puedes navegar en absoluto, la conexión se corta o funciona lentamente?')
            if active:
                response_text += f' Ticket {number}: {status}.'
        elif diagnostic and diagnostic.result_code == 'SIGNAL_DEGRADED' and response_source != 'openai_generated':
            response_text = (('The equipment is reachable in the simulator, but that does not confirm you can browse. ' if selected_language == 'en' else
                'El equipo responde en el simulador, pero eso no confirma que puedas navegar. ') + response_text)
        if (controlled_decision or intent == Intent.CONFIRM_PHYSICAL_CHECK and provider_status == 'unavailable') and ticket and ticket.status in {'OPEN','IN_PROGRESS'} and not resume_requested:
            context['workflow_state']='HANDOFF_PENDING'
        if controlled_decision and authorized_decision.action not in {Action.REQUEST_NECESSARY_EVIDENCE,Action.VERIFY_CUSTOMER_CONNECTIVITY}:
            context['pending_questions']=[]
            context['unresolved_questions']=[]
        elif controlled_decision and authorized_decision.action == Action.REQUEST_NECESSARY_EVIDENCE and '?' in response_text:
            context['pending_questions']=[authorized_decision.required_fact]
            context['unresolved_questions']=[authorized_decision.required_fact]
        context['asked_questions']=(context.get('asked_questions',[]) + [
            {'question':q,'message_id':user_message.pk,
             **({'required_fact':authorized_decision.required_fact,'reason':authorized_decision.reason} if controlled_decision else {})}
            for q in context['unresolved_questions']])[-12:]
        context['latest_diagnostic'] = context.get('diagnostic')
        context['active_ticket'] = context.get('ticket')
        provenance = {'effective_provider': settings.AI_PROVIDER if settings.AI_PROVIDER in {'demo', 'openai'} else 'unknown',
            'classification_call_attempted': classification_attempted,
            'reply_call_attempted': reply_attempted, 'fallback_used': fallback_used,
            'response_source': response_source, 'intent': intent.value}
        provenance['fallback_reason'] = fallback_reason
        provenance['answer_provider'] = 'openai' if response_source == 'openai_generated' else 'demo' if response_source == 'demo_template' else 'django'
        provenance['tool_result'] = tool_result
        provenance['operation_outcome'] = outcome
        provenance['escalation_policy'] = ('confirmed_report_existing_policy' if ticket and intent == Intent.CONFIRM_PHYSICAL_CHECK else
            'explicit_handoff_existing_policy' if ticket and human_requested else
            'inconclusive_review_existing_policy' if adaptive_ticket else 'diagnostic_assessment' if ticket else 'not_applied')
        provenance['handoff_state']=context.get('workflow_state','SELF_SERVICE')
        provenance['handoff_result']={'requested':human_requested,'accepted':bool(human_requested and ticket and ticket.status in {'OPEN','IN_PROGRESS'}),
            'ticket_created_this_turn':bool(ticket and ticket.created_at >= user_message.created_at)}
        provenance.update(model_call_attempted=classification_attempted or reply_attempted,
            model_call_succeeded=reply_succeeded if reply_attempted else classification_attempted and classification_succeeded,
            classification_succeeded=classification_succeeded, reply_succeeded=reply_succeeded,
            proposed_action=proposed_action,
            executed_action='handoff' if human_requested and ticket else 'technical_review' if adaptive_ticket else 'recheck' if tool_result['executed'] else 'reuse' if tool_result['reason'] in {'frequency_limit','no_new_evidence'} else 'none')
        provenance['decision'] = {'proposed':model_decision.model_dump(mode='json'),
            'authorized':authorized_decision.model_dump(mode='json'),
            'executed':(Action.REQUEST_TECHNICAL_REVIEW if ticket and ticket.created_at >= user_message.created_at else
                Action.REPORT_EXISTING_TICKET if ticket else Action.RUN_AUTHORIZED_RECHECK if tool_result['executed'] else
                Action.REQUEST_NECESSARY_EVIDENCE if context['pending_questions'] else
                Action.VERIFY_CUSTOMER_CONNECTIVITY if authorized_decision.action == Action.VERIFY_CUSTOMER_CONNECTIVITY else Action.ANSWER_CUSTOMER).value,
            'tool_execution':provenance['executed_action'],'tool_result':tool_result}
        provenance['reply_validated'] = reply_succeeded
        provenance['model'] = settings.OPENAI_MODEL if settings.AI_PROVIDER == 'openai' and (classification_attempted or reply_attempted) else None
        if settings.DEBUG and settings.DJANGO_ENV == 'development':
            provenance['review_predicates'] = review_trace(conversation,context,conversation.diagnostic_runs.order_by('-created_at','-pk').first())
        knowledge_trace = {'retrieved_sections':[source['section_id'] for source in knowledge['sources']],
            'retrieved_sources':[{key:source[key] for key in ('document_id','title','section_id','page','generic')} for source in knowledge['sources']],
            'equipment_model':knowledge['equipment_model'],'conflict':knowledge['conflict'],
            'source_mismatch':knowledge['source_mismatch'],
            'usage':'cited' if citations else 'retrieved_not_used' if knowledge['sources'] else 'none'}
        knowledge_trace.update(retrieval_attempted=True, retrieval_succeeded=bool(knowledge['sources']), retrieval_error=retrieval_error,
            customer_displayed=bool(displayed_citations), internal_citations_retained=bool(citations),
            citation_origin='django_local' if intent in GENERATED_INTENTS and local_citation and citations else 'model_validated' if citations else 'none',
            context_injected=reply_attempted and bool(shared_sources),
            injection_reason='injected' if reply_attempted and shared_sources else 'external_sharing_disabled' if knowledge['sources'] and not shared_sources else 'no_generation_call' if not reply_attempted else 'no_matching_sources')
        knowledge_trace['similar_cases']=[{key:item[key] for key in ('case_id','revision','score','reason')} for item in similar_cases]
        knowledge_trace['case_context_injected']=bool(reply_attempted and any(item['external_allowed'] for item in similar_cases))
        context['investigation_strategy']=strategy
        context['remaining_useful_checks']=[] if context.get('workflow_state')=='HANDOFF_PENDING' else remaining
        record_usage(conversation=conversation,cases=similar_cases,external_injected=reply_attempted)
        if settings.DEBUG and settings.DJANGO_ENV == 'development':
            trace_logger.info('chat_runtime %s', provenance)
            trace_logger.info('knowledge_runtime %s',knowledge_trace)
        assistant_message = Message.objects.create(
            conversation=conversation, sender=Message.Sender.ASSISTANT, content=response_text,
            metadata={"intent": intent.value, "provider_status": provider_status, "requires_action": requires_action,
                      "image_ids": [image["id"] for image in images],
                      "display_key": display_key,
                      'operation_outcome':outcome,
                      "context": context,
                      "provenance": provenance,
                      'knowledge':knowledge_trace,'citations':citations,
                      "diagnostic_id": diagnostic.pk if diagnostic else None,
                      "ticket_id": str(ticket.pk) if ticket else None},
        )
        result = {
            "conversation_id": conversation.pk, "message": response_text, "language": selected_language,
            "intent": intent.value, "diagnostic": diagnostic_payload(diagnostic, selected_language, display_key) if diagnostic else None,
            "ticket": {"id": str(ticket.pk), "number": ticket.number, "status": ticket.status} if ticket else None,
            "requires_action": requires_action, "provider_status": provider_status,
            "images": images,
            'operation_outcome':outcome,
            'citations':displayed_citations,
        }
        from .quick_replies import offers
        result['quick_replies'] = offers(assistant_message, selected_language)
        if settings.DEBUG and settings.DJANGO_ENV == 'development':
            public_trace = dict(knowledge_trace)
            if not session.operator.has_perm('knowledge.view_referencedocument'):
                public_trace['retrieved_sources'] = []
                public_trace['retrieved_sections'] = []
            if not session.operator.has_perm('knowledge.view_caseresolution') or not (session.operator.is_superuser or conversation.customer.organization_id and conversation.customer.organization.members.filter(pk=session.operator.pk).exists()):
                public_trace['similar_cases']=[]
            result['debug'] = {'chat':provenance, 'knowledge':public_trace}
        return result


def safe_failure_reason(error):
    allowed = {'configuration_missing','timeout','upstream_error','invalid_output','invalid_or_refused_output',
               'output_incomplete','unsupported_action','invalid_citation','unverified_manual_claim','internal_reference_disclosure','redundant_evidence_request','invalid_ticket_claim','missing_ticket_result','unexecuted_action_claim','missing_tool_reuse_reason'}
    return str(error) if isinstance(error, ProviderError) and str(error) in allowed else 'schema_validation' if isinstance(error, SchemaValidationError) else 'timeout' if isinstance(error, TimeoutError) else 'provider_error'
