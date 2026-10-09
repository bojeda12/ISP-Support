"""Estado acotado: declaraciones del cliente, observaciones y diagnósticos separados."""

from .models import Message


def conversation_context(conversation):
    previous = conversation.messages.filter(sender=Message.Sender.ASSISTANT,
        metadata__context__isnull=False).order_by('-pk').first()
    saved = previous.metadata.get('context', {}) if previous else {}
    context = {
        'reported_issue': saved.get('reported_issue'),
        'language': conversation.language,
        'shown_guides': saved.get('shown_guides', [])[-20:],
        'customer_claims': saved.get('customer_claims', [])[-8:],
        'equipment_claim': saved.get('equipment_claim'),
        'unresolved_questions': saved.get('unresolved_questions', [])[-3:],
    }
    # Compatibilidad con conversaciones anteriores a la introducción del estado.
    if not previous:
        recent = list(conversation.messages.order_by('-pk')[:50])
        for entry in reversed(recent):
            if entry.metadata.get('intent') in {'NO_INTERNET', 'SLOW_INTERNET'}:
                context['reported_issue'] = entry.metadata['intent']
            context['shown_guides'] = list(dict.fromkeys(context['shown_guides'] + entry.metadata.get('image_ids', [])))[-20:]
    run = conversation.diagnostic_runs.order_by('-created_at', '-pk').first()
    context['diagnostic'] = ({'result_code': run.result_code, 'source': run.source,
        'id': run.pk} if run else None)
    ticket = conversation.tickets.order_by('-created_at').first()
    context['ticket'] = ({'number': ticket.number, 'status': ticket.status} if ticket else None)
    photo = conversation.photos.order_by('-created_at').first()
    context['photo'] = ({'id': str(photo.pk), 'status': photo.status,
        'simulated': photo.provider == 'demo',
        'observations': [str(v)[:300] for v in photo.analysis.get('observations', [])[:5]],
        'uncertainties': [str(v)[:300] for v in photo.analysis.get('uncertainties', [])[:5]],
        'connectivity_confirmed': False} if photo else None)
    return context


def remember_claim(context, message, kind):
    context['customer_claims'] = (context['customer_claims'] + [
        {'kind': kind, 'text': message[:300], 'verified': False}])[-8:]


def contextual_reply(intent, context, language):
    """Plantillas seguras: el clasificador no genera instrucciones ni modifica equipos."""
    english = language == 'en'
    texts = {
        'PERSISTING_ISSUE': (
            "Thanks for the update. Your connection problem is still unresolved. Which accessible checks have you completed, or which device do you need help identifying?",
            "Gracias por avisar. Tu problema de conexión sigue sin resolverse. ¿Qué comprobaciones accesibles completaste o qué equipo necesitas identificar?"),
        'EQUIPMENT_CLARIFICATION': (
            "Thanks for clarifying which equipment you have. A router or modem is different from a PoE injector or outdoor CPE; I cannot verify its identity from your description. What exact model is on its label, and which indicator are you looking at? Please omit serial numbers and passwords.",
            "Gracias por aclarar qué equipo tienes. Un router o módem es distinto de un inyector PoE o una CPE exterior; no puedo verificar su identidad por tu descripción. ¿Qué modelo figura en la etiqueta y qué indicador estás mirando? Omite números de serie y contraseñas."),
        'REPORT_INDICATORS': (
            "Thanks for reporting the green lights. Local router indicators do not prove outdoor CPE connectivity. Which labeled indicator is green, and is it steady or blinking? Its meaning depends on the model.",
            "Gracias por informar que las luces están verdes. Los indicadores locales del router no prueban conectividad de la CPE exterior. ¿Qué indicador está verde y está fijo o parpadeando? Su significado depende del modelo."),
        'CLARIFY_COMPLETED_CHECKS': (
            "I understand you already tried the previous suggestion. Which accessible checks did you complete? I will record them as your report, not as verified connectivity.",
            "Entiendo que ya intentaste la sugerencia anterior. ¿Qué comprobaciones accesibles realizaste? Las registraré como tu declaración, no como conectividad verificada."),
        'EXPLAIN_POE': (
            "A PoE injector is a separate adapter that can provide power through an Ethernet cable to compatible equipment. Your router may be a different device. Do not disconnect unfamiliar cables or assume you have an injector. Can you identify a separate adapter, or share a photo without private information?",
            "Un inyector PoE es un adaptador separado que puede alimentar equipos compatibles mediante un cable Ethernet. Tu router puede ser otro dispositivo. No desconectes cables desconocidos ni supongas que tienes un inyector. ¿Ves un adaptador separado o puedes enviar una foto sin información privada?"),
        'REQUEST_PHOTO': (
            "Yes, use Attach photo to send another JPEG or PNG (up to 5 MiB). Include the equipment and indicator labels, avoiding passwords, QR codes and personal information. A photo cannot confirm connectivity.",
            "Sí, usa Attach photo para enviar otra fotografía JPEG o PNG (hasta 5 MiB). Incluye el equipo y las etiquetas de indicadores, evitando contraseñas, códigos QR y datos personales. Una foto no confirma conectividad."),
        'PHOTO_QUESTION': (
            "The meaning of a light depends on the device model and its label. Which indicator do you mean, and is it steady or blinking? A photo alone cannot confirm connectivity or equipment identity.",
            "El significado de una luz depende del modelo y su etiqueta. ¿A qué indicador te refieres y está fijo o parpadeando? Una foto por sí sola no confirma conectividad ni identidad del equipo."),
        'OTHER': (
            "We are still working on your reported connection problem. Are you describing the photographed equipment, an indicator, or checks you completed?",
            "Seguimos trabajando en tu problema de conexión. ¿Te refieres al equipo fotografiado, a un indicador o a las comprobaciones que realizaste?"),
    }
    text = texts.get(intent, texts['OTHER'])[0 if english else 1]
    if intent == 'PERSISTING_ISSUE' and context.get('ticket'):
        text = ('Your connection problem remains recorded for technical review. You do not need to repeat the same checks now.' if english else
                'Tu problema de conexión sigue registrado para revisión técnica. No necesitas repetir las mismas comprobaciones ahora.')
    photo = context.get('photo')
    if intent in {'PHOTO_QUESTION', 'EQUIPMENT_CLARIFICATION'} and photo:
        prefix = ('Latest photo analysis (simulated): ' if photo['simulated'] else 'Latest photo observations: ') if english else ('Último análisis de foto (simulado): ' if photo['simulated'] else 'Observaciones de la última foto: ')
        text += ' ' + prefix + ' '.join(photo['observations'] + photo['uncertainties'])
    diagnostic = context.get('diagnostic')
    if diagnostic and diagnostic['result_code'] == 'CPE_UNREACHABLE':
        if diagnostic['source'] == 'simulation':
            text += ' ' + ('The latest simulated diagnostic reports CPE_UNREACHABLE; the cause is not confirmed.' if english else 'El último diagnóstico simulado indica CPE_UNREACHABLE; la causa no está confirmada.')
    if context.get('ticket'):
        ticket = context['ticket']
        text += f" {'Ticket' if english else 'Ticket'} {ticket['number']}: {ticket['status']}."
    return text
