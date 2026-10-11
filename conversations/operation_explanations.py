"""Presentación de resultados confirmados; no autoriza ni ejecuta operaciones."""


def operation_outcome(run, tool_result, ticket, customer_message):
    diagnostic = None
    if run:
        diagnostic = {
            'id': run.pk, 'completed_at': run.completed_at.isoformat() if run.completed_at else None,
            'result_code': run.result_code, 'source': run.source,
            'execution': 'new' if tool_result.get('executed') else 'reused',
        }
    ticket_result = None
    if ticket:
        ticket_result = {**ticket, 'action':'existing'} if isinstance(ticket, dict) else {
            'number': ticket.number, 'status': ticket.status,
            'action': 'created' if ticket.created_at >= customer_message.created_at else 'existing'}
    return {'diagnostic': diagnostic, 'reason': tool_result.get('reason'), 'ticket':ticket_result}


def validate_operation_claims(answer, outcome):
    import re
    from .ai import ProviderError, normalize
    ticket = outcome.get('ticket')
    if ticket and ticket['action'] == 'existing' and re.search(
            r"(i opened|i.ve opened|i created|i.ve created|he abierto|he creado|abri).{0,40}(ticket|incidencia)", normalize(answer)):
        raise ProviderError('invalid_ticket_claim')


def explain_operation(context, language):
    outcome = context.get('operation_outcome', {})
    diagnostic, ticket = outcome.get('diagnostic'), outcome.get('ticket')
    english = language == 'en'
    parts = []
    if context.get('reported_checks_this_turn'):
        if context.get('completed_report_this_turn'):
            parts.append('Thank you for completing the accessible checks you reported.' if english else
                         'Gracias por realizar las comprobaciones accesibles que reportaste.')
        else:
            parts.append('Thank you for telling me about the checks you tried.' if english else
                         'Gracias por contarme las comprobaciones que intentaste.')
    photos = context.get('photos', [])
    if photos:
        photo = photos[0]
        if photo.get('simulated'):
            parts.append('I received your photo; its analysis is simulated and does not verify the pictured equipment.' if english else
                         'Recibí tu foto; su análisis es simulado y no verifica el equipo fotografiado.')
        elif photo.get('observations') and photo.get('status') == 'COMPLETED':
            parts.append(('In the photo: ' if english else 'En la foto: ') + photo['observations'][0])
        else:
            parts.append('I received your photo.' if english else 'Recibí tu foto.')
        parts.append('A photo cannot confirm working hardware or Internet connectivity.' if english else
                     'Una foto no confirma que el equipo funcione ni que haya conexión a Internet.')
    if diagnostic:
        new = diagnostic['execution'] == 'new'
        simulated = diagnostic['source'] == 'simulation'
        if new:
            parts.append(('I checked your connection again in the simulator.' if simulated else 'I checked your connection again.') if english else
                         ('Volví a comprobar tu conexión en el simulador.' if simulated else 'Volví a comprobar tu conexión.'))
        else:
            parts.append(('I used the latest available simulated network check; no new measurement was taken.' if simulated else
                          'I used the latest available network check; no new measurement was taken.') if english else
                         ('Utilicé la última comprobación de red simulada disponible; no se realizó una medición nueva.' if simulated else
                          'Utilicé la última comprobación de red disponible; no se realizó una medición nueva.'))
        if diagnostic['result_code'] == 'CPE_UNREACHABLE':
            parts.append('The outdoor equipment is still not responding; the cause is not confirmed.' if english else
                         'El equipo exterior sigue sin responder; la causa no está confirmada.')
        elif diagnostic['result_code'] == 'NO_FAULT_DETECTED':
            parts.append('The result shows no connectivity fault; it does not confirm a repair on real equipment.' if english else
                         'El resultado no muestra una falla de conectividad; no confirma una reparación en equipos reales.')
        else:
            from .replies import reply
            parts.append(reply(diagnostic['result_code'], language))
    elif outcome.get('reason') in {'operation_unavailable','simulation_unavailable','stale_result_rate_limited'}:
        parts.append('I could not complete a network check, so I cannot confirm a new result.' if english else
                     'No pude completar la comprobación de red, por lo que no puedo confirmar un resultado nuevo.')
    if outcome.get('reason') in {'frequency_limit', 'stale_result_rate_limited'}:
        parts.append('The recheck rate limit was reached.' if english else 'Se alcanzó el límite de comprobaciones.')
    if ticket:
        if ticket['action'] == 'created':
            parts.append(('Since the issue persists after your reported checks, I opened a support ticket for technical review.' if context.get('reported_checks_this_turn') else
                          'I opened a support ticket for technical review.') if english else
                         ('Como el problema persiste después de las comprobaciones que reportaste, abrí un ticket para revisión técnica.' if context.get('reported_checks_this_turn') else
                          'Abrí un ticket para revisión técnica.'))
        else:
            parts.append('Your issue remains recorded under the existing support ticket.' if english else
                         'Tu incidencia sigue registrada en el ticket de soporte existente.')
        parts.append(f"Ticket {ticket['number']}: {ticket['status']}.")
        parts.append('You do not need to repeat the same checks. No visit or repair has been confirmed.' if english else
                     'No necesitas repetir las mismas comprobaciones. No hay visita técnica ni reparación confirmada.')
    elif diagnostic and diagnostic['result_code'] == 'NO_FAULT_DETECTED':
        parts.append('Can you open a website now?' if english else '¿Puedes abrir una página web ahora?')
    return ' '.join(parts)
