"""Opciones de presentación; toda operación sigue pasando por el orquestador."""
from django.core.exceptions import ValidationError
from .models import Message


# Etiqueta breve y declaración explícita: nunca enviar un «sí» sin contexto.
CHOICES = {
    'no_internet': ('No Internet', 'Sin Internet', 'I have no Internet.', 'No tengo Internet.'),
    'slow': ('Slow Internet', 'Internet lento', 'My Internet is slow.', 'Mi Internet está lento.'),
    'drops': ('Connection Drops', 'La conexión se corta', 'My connection keeps dropping intermittently.', 'Mi conexión se corta de forma intermitente.'),
    'no_power': ("Equipment Won’t Turn On", 'El equipo no enciende', "My equipment won't turn on; it has no power.", 'Mi equipo no enciende; no tiene energía.'),
    'human': ('Talk to a Technician', 'Hablar con un técnico', 'I want to talk to a technician.', 'Quiero hablar con un técnico.'),
    'checked': ('Yes, I checked', 'Sí, lo revisé', '', ''),
    'help': ('I need help', 'Necesito ayuda', 'I need help with the check you just requested.', 'Necesito ayuda con la comprobación que acabas de pedir.'),
    'unsure': ("I’m not sure", 'No estoy seguro', 'I am not sure about the check you just requested.', 'No estoy seguro de la comprobación que acabas de pedir.'),
    'cannot': ("I can’t check", 'No puedo revisarlo', 'I cannot safely perform the check you just requested.', 'No puedo realizar de forma segura la comprobación que acabas de pedir.'),
    'continue': ('Continue troubleshooting', 'Continuar comprobaciones', 'I want to continue troubleshooting myself.', 'Quiero retomar las comprobaciones por mi cuenta.'),
}
ISSUES = ('no_internet', 'slow', 'drops', 'no_power', 'human')
SCOPES = {
    'basic_checks': ('I checked the accessible power, the PoE equipment if present, and the Internet cables. Everything is connected, but I still have no Internet.', 'Revisé la alimentación accesible, el equipo PoE si está presente y los cables de Internet. Todo está conectado, pero sigo sin Internet.'),
    'power': ('I checked the accessible power connection as requested.', 'Revisé la conexión de alimentación accesible que me pediste.'),
    'cable_path': ('I checked the accessible Internet cables as requested.', 'Revisé los cables de Internet accesibles que me pediste.'),
}


def offers(message=None, language='en'):
    codes = ISSUES
    scope = None
    if message:
        meta = message.metadata
        context = meta.get('context', {})
        if meta.get('ticket_id') or context.get('workflow_state') == 'HANDOFF_PENDING':
            if (context.get('diagnostic') or {}).get('result_code') not in {'SIGNAL_DEGRADED', 'PERFORMANCE_DEGRADED'}:
                return []
            codes = ('no_internet', 'slow', 'drops', 'human') if context.get('support_preference') == 'self_service' else ('continue',)
            index = 1 if language == 'es' else 0
            return [{'id': code, 'label': CHOICES[code][index],
                'labels': {'en': CHOICES[code][0], 'es': CHOICES[code][1]},
                'message': CHOICES[code][index + 2], 'question_message_id': message.pk,
                'scope': None} for code in codes]
        pending = context.get('unresolved_questions', [])
        scope = pending[0] if pending and pending[0] in SCOPES else None
        if context.get('reported_issue') == 'NO_INTERNET' and context.get('shown_guides') and context.get('issue_category') in {None, 'unknown', 'NO_INTERNET'}:
            scope = 'basic_checks'
        if scope or pending or meta.get('requires_action') in {'REVIEW_GUIDE', 'REVIEW_SAFE_CHECKS'}:
            codes = (('checked',) if scope else ()) + ('help', 'unsure', 'cannot', 'human')
        else:
            codes = ('human',)
    index = 1 if language == 'es' else 0
    return [{'id': code, 'label': CHOICES[code][index], 'labels': {'en': CHOICES[code][0], 'es': CHOICES[code][1]},
             'message': SCOPES[scope][index] if code == 'checked' else CHOICES[code][index + 2],
             'question_message_id': message.pk if message else None,
             'scope': scope} for code in codes]


def resolve(selection, conversation, language):
    if not isinstance(selection, dict) or set(selection) != {'id', 'question_message_id'}:
        raise ValidationError('Invalid quick reply.')
    latest = conversation.messages.filter(sender=Message.Sender.ASSISTANT).order_by('-pk').first() if conversation else None
    reference = selection['question_message_id']
    if reference is not None and (not latest or type(reference) is not int or reference != latest.pk):
        raise ValidationError('This question is no longer available. Refresh the conversation.')
    candidates = offers(latest, language) if reference is not None else offers(language=language)
    if reference is None and selection['id'] not in ISSUES:
        raise ValidationError('This reply requires its original question.')
    for entry in candidates:
        if entry['id'] == selection['id']:
            return entry
    raise ValidationError('This quick reply is not available for this question.')
