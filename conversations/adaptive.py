"""Estado de evidencia y herramienta autorizada; ninguna propuesta equivale a permiso."""
import re
from time import monotonic
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from .ai import Intent, normalize, ProviderError
from .models import Conversation


class DiagnosticRateLimit(ValidationError):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__('Diagnostic frequency limit reached.', code='diagnostic_rate_limited')


def uncertain_statement(message):
    return bool(re.search(r"not sure|not certain|unsure|uncertain|can't tell|cannot tell|don't know|do not know|haven't checked|have not checked|not checked|no estoy segur|no se si|no se que|no tengo claro|no he revisado|no he comprobado|tengo dudas", normalize(message)))


def explicit_completed_report(message):
    return not uncertain_statement(message) and bool(re.search(r"\b(checked|inspected|verified|revise|revisado|comprobe|comprobado|verifique|verificado)\b", normalize(message)))


def reported_attempt(message):
    text = normalize(message)
    if re.search(r"haven't (tried|checked)|have not (tried|checked)|did not (try|check)|no he (intentado|revisado)|no intente", text):
        return False
    return bool(re.search(r'\b(tried|attempted|checked|inspected|verified|intente|intentado|revise|revisado|comprobe|comprobado)\b',text))


def validate_ticket_claim(answer, ticket):
    numbers = re.findall(r'\bISP-[A-Z0-9]+\b',answer,re.I)
    if any(not ticket or number.upper() != ticket['number'].upper() for number in numbers):
        raise ProviderError('invalid_ticket_claim')
    if not ticket and re.search(r"\b(i have created|i've created|i opened|he creado|abri)\b.{0,30}\b(ticket|incidencia)\b",normalize(answer)):
        raise ProviderError('invalid_ticket_claim')


def validate_tool_reply(answer, tool_result, ticket):
    """No aceptar una operación ya resuelta como mera propuesta futura."""
    if ticket and ticket['number'] not in answer:
        raise ProviderError('missing_ticket_result')
    claims = re.sub(r'\bno new (network check|measurement|diagnostic)\b|\bno se (realiz[oó]|tom[oó]) (una )?nueva medici[oó]n\b', '', answer, flags=re.I)
    if not tool_result.get('executed') and re.search(
        r"(checked|tested).{0,30}(connection|network).{0,12}again|new (network check|measurement|diagnostic)"
        r"|volv[ií].{0,20}(comprobar|revisar).{0,20}conexi[oó]n|nuevo diagn[oó]stico|nueva medici[oó]n",
        claims, re.I):
        raise ProviderError('unexecuted_action_claim')
    if tool_result.get('reason') == 'frequency_limit' and not re.search(r'limit|l[ií]mite',answer,re.I):
        raise ProviderError('missing_tool_reuse_reason')
    if tool_result.get('diagnostic_id') and re.search(
        r'(next step|should|might|need to|will|going to).{0,85}(recheck|run.{0,25}(check|diagnostic))'
        r'|(running|performing).{0,30}recheck.{0,30}(might|could|will)'
        r'|recheck.{0,20}(is planned|is pending|will be)'
        r'|(siguiente paso|deber[ií]a|habr[ií]a que|vamos a).{0,70}(comprobaci[oó]n|diagn[oó]stico|revisar)',
        answer, re.I):
        raise ProviderError('unexecuted_action_claim')


def guard_interpretation(parsed, message, context):
    if re.search(r"cannot access|can't access|inaccessible|no puedo acceder|no es accesible", normalize(message)):
        parsed = parsed.model_copy(update={'additional_checks':'unavailable'})
    if parsed.support_preference == 'human':
        return parsed.model_copy(update={'intent':Intent.REQUEST_TECHNICIAN})
    # La misma confirmación declarada ya admitida por CONFIRM_PHYSICAL_CHECK
    # debe alcanzar esa ruta aunque el modelo la clasifique como comentario/foto.
    # Incertidumbre del cliente conserva la ruta inconclusa; nunca verifica cableado.
    if (context.get('reported_issue') == 'NO_INTERNET' and context.get('shown_guides')
            and explicit_completed_report(message)
            and (parsed.checks_attempted or parsed.intent == Intent.CONFIRM_PHYSICAL_CHECK)):
        return parsed.model_copy(update={'intent':Intent.CONFIRM_PHYSICAL_CHECK,
            'check_evidence':'completed_report','next_action':'recheck' if parsed.decision is not None else parsed.next_action,'question_kind':'none'})
    if uncertain_statement(message) or parsed.check_evidence == 'attempted_uncertain':
        if parsed.intent in {Intent.EXPLAIN_POE,Intent.EQUIPMENT_CLARIFICATION}:
            return parsed.model_copy(update={'check_evidence':'attempted_uncertain','next_action':'ask_question'})
        if parsed.intent != Intent.REQUEST_TECHNICIAN:
            return parsed.model_copy(update={'intent':Intent.PHOTO_QUESTION if context.get('photo') else Intent.CLARIFY_COMPLETED_CHECKS,
                'check_evidence':'attempted_uncertain',
                'next_action':parsed.next_action if parsed.next_action in {'ask_question','request_photo'} else 'ask_question'})
        return parsed.model_copy(update={'check_evidence':'attempted_uncertain'})
    if parsed.intent == Intent.CONFIRM_PHYSICAL_CHECK and not (explicit_completed_report(message) or parsed.check_evidence == 'completed_report'):
        return parsed.model_copy(update={'intent':Intent.CLARIFY_COMPLETED_CHECKS,'next_action':'ask_question'})
    return parsed


def demo_proposal(parsed, context):
    if (parsed.check_evidence == 'attempted_uncertain' or parsed.intent == Intent.PHOTO_QUESTION and context.get('reported_issue')) and len(context.get('photos',[])) == 1 and 'front_photo' not in context.get('pending_questions',[]) and context['photo']['id'] not in context.get('discussed_photo_ids',[]):
        return parsed.model_copy(update={'next_action':'request_photo','question_kind':'front_photo'})
    if context.get('photo') and len(context.get('photos',[])) > 1 and 'front_photo' in context.get('pending_questions',[]) and context['photo']['status'] == 'COMPLETED':
        return parsed.model_copy(update={'next_action':'recheck'})
    return parsed


def review_eligibility(conversation, context, run):
    """Política nueva explícita: intentos inconclusos suficientes para revisión, no verificación física."""
    if not settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW:
        return False
    if not run or run.source != 'simulation' or run.result_code != 'CPE_UNREACHABLE':
        return False
    if not run.completed_at or run.completed_at < timezone.now() - timedelta(seconds=settings.CHAT_REVIEW_DIAGNOSTIC_MAX_AGE_SECONDS):
        return False
    if context.get('reported_issue') != 'NO_INTERNET' or not context.get('shown_guides'):
        return False
    attempted = [item for item in context.get('customer_reported_checks',[]) if item.get('attempted') or item.get('status') == 'customer_reported_complete' or reported_attempt(item.get('text',''))]
    latest = list(conversation.diagnostic_runs.order_by('-created_at','-pk').values_list('result_code','source')[:2])
    if not attempted or len(latest) < 2 or any(code != 'CPE_UNREACHABLE' or source != 'simulation' for code,source in latest):
        return False
    reviewed = [photo for photo in context.get('photos',[]) if photo['status'] == 'COMPLETED']
    # Dos fotos sin intento declarado nunca satisfacen esta política. La revisión
    # técnica resuelve la incertidumbre; las fotos no certifican cableado ni conexión.
    return len(reviewed) >= settings.CHAT_REVIEW_MIN_REVIEWED_PHOTOS or context.get('additional_checks') == 'unavailable' or context.get('evidence_exhausted') and len(context.get('supplied_evidence',[])) >= 3


def progress_state(context, parsed, message, message_id):
    """Una respuesta consume la pregunta pendiente; incertidumbre no significa falta de intento."""
    pending = context.get('pending_questions', [])
    answered = list(context.get('answered_questions', []))
    responsive = parsed.answers_pending or parsed.intent in {
        Intent.ANSWER_CLARIFICATION, Intent.EQUIPMENT_CLARIFICATION,
        Intent.REPORT_INDICATORS, Intent.CLARIFY_COMPLETED_CHECKS}
    if pending and message.strip() and responsive:
        answered += [{'question':q, 'answer':message[:200], 'verified':False,
                      'message_id':message_id} for q in pending]
    attempts = any(v.get('attempted') or v.get('status') == 'customer_reported_complete'
                   for v in context.get('customer_reported_checks', []))
    reviewed = sum(p['status'] == 'COMPLETED' for p in context.get('photos', []))
    # Nunca basta frustración o dos imágenes: exigimos incidencia, guía e intento.
    supplied = list(dict.fromkeys(context.get('supplied_evidence',[]) + parsed.supplied_evidence))
    if 'ports' in supplied and 'indicators' in supplied and not any(v['question']=='indicator_label' for v in answered):
        answered.append({'question':'indicator_label','answer':'Customer supplied port and indicator observations; meaning remains unverified.','verified':False,'message_id':message_id})
    exhausted = parsed.evidence_exhausted or context.get('evidence_exhausted',False)
    diminishing = bool(context.get('reported_issue') == 'NO_INTERNET'
        and context.get('shown_guides') and attempts and (reviewed >= 2 or exhausted and len(supplied) >= 3))
    return {'answered_questions':answered[-12:],
            'unresolved_questions':[] if responsive else pending,
            'pending_questions':[] if responsive else pending,
            'diminishing_customer_checks':diminishing,
            'supplied_evidence':supplied,'evidence_exhausted':exhausted}


def review_trace(conversation, context, run):
    latest = list(conversation.diagnostic_runs.order_by('-created_at','-pk')
                  .values_list('result_code','source')[:2])
    return {
        'policy_enabled':settings.CHAT_ALLOW_INCONCLUSIVE_REVIEW,
        'simulated_cpe_failure':bool(run and run.source == 'simulation' and run.result_code == 'CPE_UNREACHABLE'),
        'fresh_result':bool(run and run.completed_at and run.completed_at >= timezone.now()-timedelta(seconds=settings.CHAT_REVIEW_DIAGNOSTIC_MAX_AGE_SECONDS)),
        'unresolved_outage':context.get('reported_issue') == 'NO_INTERNET',
        'guide_presented':bool(context.get('shown_guides')),
        'reported_attempt':any(v.get('attempted') or v.get('status') == 'customer_reported_complete' or reported_attempt(v.get('text','')) for v in context.get('customer_reported_checks',[])),
        'two_failed_measurements':len(latest) == 2 and all(code == 'CPE_UNREACHABLE' and source == 'simulation' for code,source in latest),
        'available_evidence_reviewed':sum(p['status'] == 'COMPLETED' for p in context.get('photos',[])) >= settings.CHAT_REVIEW_MIN_REVIEWED_PHOTOS or context.get('additional_checks') == 'unavailable' or bool(context.get('evidence_exhausted') and len(context.get('supplied_evidence',[])) >= 3),
    }


def evidence_state(context, parsed, message, message_id):
    state = {key:context.get(key, [])[-8:] for key in ('customer_reported_checks','confirmed_completed_checks','uncertain_checks')}
    if parsed.check_evidence == 'attempted_uncertain':
        state['uncertain_checks'].append({'message_id':message_id,'text':message[:250],'verified':False})
        state['customer_reported_checks'].append({'message_id':message_id,'status':'attempted_uncertain','text':message[:250],'verified':False,'attempted':reported_attempt(message) or parsed.checks_attempted})
    elif parsed.intent == Intent.CONFIRM_PHYSICAL_CHECK or parsed.check_evidence == 'completed_report':
        item={'message_id':message_id,'text':message[:250],'verified':False,'status':'customer_reported_complete'}
        state['customer_reported_checks'].append(item)
        state['confirmed_completed_checks'].append(item)
        # No se borra la incertidumbre sobre otros elementos de la instalación.
    elif parsed.checks_attempted or reported_attempt(message):
        state['customer_reported_checks'].append({'message_id':message_id,'status':'attempted','text':message[:250],'verified':False,'attempted':True})
    return {**{key:value[-8:] for key,value in state.items()},
        'evidence_reports':{**context.get('evidence_reports',{}),**{key:{'text':message[:200],'verified':False,'message_id':message_id} for key in parsed.supplied_evidence}},
        'supplied_evidence':list(dict.fromkeys(context.get('supplied_evidence',[]) + parsed.supplied_evidence)),
        'evidence_exhausted':parsed.evidence_exhausted or context.get('evidence_exhausted',False),
        'additional_checks':parsed.additional_checks if parsed.additional_checks != 'available' else context.get('additional_checks','available')}


def factual_summary(context):
    result = []
    for item in context.get('customer_reported_checks', [])[-4:]:
        if item.get('status') == 'attempted':
            result.append('Customer-reported attempt (not verified): ' + item['text'])
    for item in context.get('confirmed_completed_checks', [])[-4:]:
        result.append('Customer-reported completed check (not independently verified): ' + item['text'])
    for item in context.get('uncertain_checks', [])[-3:]:
        result.append('Customer uncertainty: ' + item['text'])
    for photo in context.get('photos', [])[:3]:
        result.append(('SIMULATED photo, pixels not verified: ' if photo['simulated'] else 'Uncertain visual observations: ') + ' '.join(photo['observations'])[:400])
    return result


@transaction.atomic
def authorized_recheck(*, session, conversation, message, new_photo=False, completed=False, explicit_request=False, new_issue=False):
    from .services import ensure_session
    from .services import run_diagnostic
    from customers.models import InternetService
    from diagnostics.models import DiagnosticRun
    ensure_session(session)
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    if conversation.internet_service_id != session.internet_service_id or conversation.customer_id != session.internet_service.customer_id or conversation.status != 'OPEN':
        raise PermissionDenied('Diagnostic is outside the authorized conversation.')
    previous = conversation.diagnostic_runs.order_by('-created_at','-pk').first()
    if previous and previous.source != 'simulation':
        raise PermissionDenied('Only simulated read-only diagnostics are permitted.')
    InternetService.objects.select_for_update().get(pk=session.internet_service_id)
    if completed:
        last_reply = conversation.messages.filter(sender='assistant').order_by('-pk').first()
        saved = last_reply.metadata.get('context',{}) if last_reply else {}
        completed = normalize(message) not in {normalize(item.get('text','')) for item in saved.get('confirmed_completed_checks',[])}
    runs = conversation.diagnostic_runs
    recent = runs.filter(created_at__gte=timezone.now()-timedelta(seconds=settings.CHAT_DIAGNOSTIC_WINDOW_SECONDS)).count()
    hourly = DiagnosticRun.objects.filter(internet_service_id=session.internet_service_id,created_at__gte=timezone.now()-timedelta(hours=1)).count()
    reason = None
    if previous and not (new_photo or completed or explicit_request or new_issue):
        reason = 'no_new_evidence'
    elif recent >= settings.CHAT_DIAGNOSTIC_MAX_PER_WINDOW or hourly >= settings.CHAT_DIAGNOSTIC_MAX_PER_HOUR:
        reason = 'frequency_limit'
    if reason:
        if previous is None:
            from math import ceil
            now = timezone.now()
            deadlines = []
            if recent >= settings.CHAT_DIAGNOSTIC_MAX_PER_WINDOW:
                oldest = runs.filter(created_at__gte=now-timedelta(seconds=settings.CHAT_DIAGNOSTIC_WINDOW_SECONDS)).order_by('created_at').first()
                if oldest:
                    deadlines.append(oldest.created_at + timedelta(seconds=settings.CHAT_DIAGNOSTIC_WINDOW_SECONDS))
            if hourly >= settings.CHAT_DIAGNOSTIC_MAX_PER_HOUR:
                oldest = DiagnosticRun.objects.filter(internet_service_id=session.internet_service_id,created_at__gte=now-timedelta(hours=1)).order_by('created_at').first()
                if oldest:
                    deadlines.append(oldest.created_at + timedelta(hours=1))
            raise DiagnosticRateLimit(max(1,ceil((max(deadlines)-now).total_seconds())) if deadlines else 1)
        return previous, {'executed':False,'reason':reason,'result_code':previous.result_code,'source':previous.source,
            'diagnostic_id':previous.pk,'completed_at':previous.completed_at.isoformat() if previous.completed_at else None,
            'fresh':bool(previous.completed_at and previous.completed_at >= timezone.now()-timedelta(seconds=settings.CHAT_REVIEW_DIAGNOSTIC_MAX_AGE_SECONDS))}
    started = monotonic()
    run = run_diagnostic(internet_service=session.internet_service,conversation=conversation)
    if monotonic() - started > settings.CHAT_DIAGNOSTIC_TIMEOUT_SECONDS:
        raise ValidationError('Simulated diagnostic exceeded its time budget.')
    if run.source != 'simulation':
        raise PermissionDenied('Only simulated read-only diagnostics are permitted.')
    return run, {'executed':True,'reason':'authorized_simulation','result_code':run.result_code,'source':run.source,'diagnostic_id':run.pk,
        'completed_at':run.completed_at.isoformat(),'fresh':True,
        'metrics':{key:value for key,value in run.metrics.items() if key != 'ap_identifier'}}


def adaptive_reply(context, language, requesting_photo=False):
    from .context import photo_reply
    en = language == 'en'
    text = photo_reply(context,language,'connections')
    if requesting_photo:
        text += ' ' + ('Could you show the front of that device, without private information, so we can inspect its labeled indicators?' if en else
                        '¿Puedes mostrar la parte frontal de ese equipo, sin información privada, para revisar sus indicadores identificados?')
    else:
        text += ' ' + ('Which connection are you uncertain about?' if en else '¿Sobre qué conexión tienes dudas?')
    return text
