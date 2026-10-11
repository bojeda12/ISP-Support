"""Contrato de decisión: las propuestas no otorgan autorización operacional."""
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class Action(StrEnum):
    ANSWER_CUSTOMER = 'ANSWER_CUSTOMER'
    REQUEST_NECESSARY_EVIDENCE = 'REQUEST_NECESSARY_EVIDENCE'
    RUN_AUTHORIZED_RECHECK = 'RUN_AUTHORIZED_RECHECK'
    REQUEST_TECHNICAL_REVIEW = 'REQUEST_TECHNICAL_REVIEW'
    REPORT_EXISTING_TICKET = 'REPORT_EXISTING_TICKET'
    VERIFY_CUSTOMER_CONNECTIVITY = 'VERIFY_CUSTOMER_CONNECTIVITY'


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Action
    required_fact: str = Field(default='', max_length=80)
    reason: str = Field(default='', max_length=300)


def select_decision(parsed, context, run, *, policy_enabled):
    """Prioriza mediciones útiles; la ejecución conserva permisos, límites y elegibilidad."""
    proposed = parsed.decision or Decision(action={
        'ask_question':Action.REQUEST_NECESSARY_EVIDENCE,
        'request_photo':Action.REQUEST_NECESSARY_EVIDENCE,
        'recheck':Action.RUN_AUTHORIZED_RECHECK,
        'recommend_escalation':Action.REQUEST_TECHNICAL_REVIEW,
    }.get(parsed.next_action, Action.ANSWER_CUSTOMER), required_fact=parsed.question_kind)
    ticket = context.get('ticket')
    if ticket and ticket['status'] in {'OPEN','IN_PROGRESS'} and parsed.support_preference != 'self_service':
        return proposed, Decision(action=Action.REPORT_EXISTING_TICKET, reason='Existing authorized ticket; no further questionnaire.')
    if parsed.support_preference == 'human' or parsed.intent == 'REQUEST_TECHNICIAN':
        return proposed, Decision(action=Action.REQUEST_TECHNICAL_REVIEW, reason='Explicit human assistance request; existing handoff policy applies.')
    if not run and parsed.intent in {'NO_INTERNET','SLOW_INTERNET'}:
        return proposed, Decision(action=Action.RUN_AUTHORIZED_RECHECK, reason='Initial authorized service assessment required.')
    if not policy_enabled or not run or context.get('reported_issue') != 'NO_INTERNET' or parsed.issue_category not in {'unknown','NO_INTERNET'}:
        return proposed, proposed
    attempts = any(v.get('attempted') or v.get('status') == 'customer_reported_complete'
                   for v in context.get('customer_reported_checks', []))
    if run.result_code == 'NO_FAULT_DETECTED':
        return proposed, Decision(action=Action.VERIFY_CUSTOMER_CONNECTIVITY, reason='Simulation cannot establish customer browsing restoration.')
    if run.result_code == 'CPE_UNREACHABLE' and (attempts or context.get('additional_checks') == 'unavailable'):
        return proposed, Decision(action=Action.RUN_AUTHORIZED_RECHECK, reason='Guided checks attempted; read-only measurement is more useful than port labels.')
    known = set(context.get('supplied_evidence', []))
    answered = {v['question'] for v in context.get('answered_questions', [])}
    fact = proposed.required_fact
    if proposed.action == Action.REQUEST_NECESSARY_EVIDENCE:
        if fact in known or fact in answered or fact not in {'power','cable_path','physical_access'} or context.get('evidence_exhausted'):
            return proposed, Decision(action=Action.ANSWER_CUSTOMER, reason='Requested detail does not change the generic connectivity action or is already supplied.')
        if not proposed.reason:
            return proposed, Decision(action=Action.ANSWER_CUSTOMER, reason='No material decision value supplied for the question.')
    return proposed, proposed


def fallback_answer(context, language, decision, run=None, ticket=None):
    """Resumen de hechos y resultado autorizado, sin reiniciar un cuestionario."""
    from .replies import reply
    if context.get('operation_outcome') and (context.get('reported_checks_this_turn') or ticket):
        from .operation_explanations import explain_operation
        return explain_operation(context, language)
    english = language == 'en'
    parts = []
    if context.get('photos'):
        simulated = context['photos'][0].get('simulated', True)
        parts.append(('The photo analysis is simulated; its contents are not verified.' if english else
                      'El análisis de la foto es simulado; su contenido no está verificado.') if simulated else
                     ('The photo provides limited visual evidence; it cannot confirm Internet connectivity.' if english else
                      'La foto aporta evidencia visual limitada; no confirma conectividad a Internet.'))
    reports = context.get('supplied_evidence', [])
    if reports:
        labels = {'ports':('cable connections','conexiones de cables'),'cable_path':('cable path','recorrido de cables'),
                  'power':('power','alimentación'),'indicators':('lights','luces'),'equipment_role':('device/cable purpose','función de equipos/cables')}
        facts = ', '.join(labels[k][0 if english else 1] for k in reports if k in labels)
        parts.append(('You reported ' if english else 'Has informado sobre ') + facts +
                     ('. These local observations do not prove Internet access.' if english else '. Estas observaciones locales no prueban acceso a Internet.'))
    if run:
        if context.get('tool_result',{}).get('reason') == 'frequency_limit':
            parts.append('The recheck rate limit was reached; the existing result was reused.' if english else
                         'Se alcanzó el límite de comprobaciones; se reutilizó el resultado existente.')
        if run.result_code == 'CPE_UNREACHABLE':
            parts.append('The available simulated check cannot reach the outdoor equipment; the cause remains unconfirmed.' if english else
                         'La comprobación simulada disponible no alcanza el equipo exterior; la causa sigue sin confirmarse.')
        else:
            parts.append(reply(run.result_code, language))
    if ticket:
        parts.append(reply('ticket_status', language, number=ticket.number, status=ticket.status))
    elif decision.action == Action.VERIFY_CUSTOMER_CONNECTIVITY:
        parts.append('Can you open a website now?' if english else '¿Puedes abrir una página web ahora?')
    elif decision.action == Action.REQUEST_NECESSARY_EVIDENCE:
        questions={
            'power':('Is the accessible PoE power indicator on?','¿Está encendido el indicador de alimentación del PoE accesible?'),
            'cable_path':('Where does the accessible Internet cable lead?','¿Adónde va el cable de Internet accesible?'),
            'physical_access':('Can you safely see the equipment without moving it?','¿Puedes ver el equipo de forma segura sin moverlo?'),
        }
        if decision.required_fact in questions:
            parts.append(questions[decision.required_fact][0 if english else 1])
    return ' '.join(parts) or ('I have recorded your report; connectivity remains unconfirmed.' if english else
                              'He registrado tu información; la conectividad sigue sin confirmarse.')
