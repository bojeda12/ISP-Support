"""Estado acotado: declaraciones del cliente, observaciones y diagnósticos separados."""

import re
import json

from .models import Message


def conversation_context(conversation):
    previous = conversation.messages.filter(sender=Message.Sender.ASSISTANT,
        metadata__context__isnull=False).order_by('-pk').first()
    saved = previous.metadata.get('context', {}) if previous else {}
    latest_customer = conversation.messages.filter(sender=Message.Sender.CUSTOMER).order_by('-pk').first()
    context = {
        'reported_issue': saved.get('reported_issue'),
        'customer_response': latest_customer.metadata.get('quick_reply') if latest_customer else None,
        'decision_contract': saved.get('decision_contract', False),
        'service_id': conversation.internet_service_id,
        'language': conversation.language,
        'shown_guides': saved.get('shown_guides', [])[-20:],
        'customer_claims': [{**item,'text':str(item.get('text',''))[:180]} for item in saved.get('customer_claims', [])[-8:]],
        'equipment_claim': saved.get('equipment_claim'),
        'unresolved_questions': saved.get('unresolved_questions', [])[-3:],
        'answered_questions': saved.get('answered_questions', [])[-12:],
        'diminishing_customer_checks': saved.get('diminishing_customer_checks', False),
        'supplied_evidence': saved.get('supplied_evidence', [])[-5:],
        'evidence_reports':saved.get('evidence_reports',{}),
        'evidence_exhausted': saved.get('evidence_exhausted',False),
        'workflow_state': saved.get('workflow_state','SELF_SERVICE'),
        'support_preference': saved.get('support_preference','unchanged'),
        'asked_questions': saved.get('asked_questions',[]) [-12:],
        'issue_category': saved.get('issue_category','unknown'),
        'investigation_strategy': saved.get('investigation_strategy'),
        'remaining_useful_checks':saved.get('remaining_useful_checks',[])[:8],
        'completed_checks': saved.get('completed_checks', [])[-4:],
        'discussed_photo_ids': saved.get('discussed_photo_ids', [])[-6:],
        'troubleshooting_stage': saved.get('troubleshooting_stage','identify_issue'),
        'customer_reported_checks': saved.get('customer_reported_checks', [])[-8:],
        'confirmed_completed_checks': saved.get('confirmed_completed_checks', [])[-8:],
        'uncertain_checks': saved.get('uncertain_checks', [])[-8:],
        'next_recommended_action': saved.get('next_recommended_action','none'),
        'additional_checks': saved.get('additional_checks','available'),
        'trusted_verified_checks': saved.get('trusted_verified_checks',[])[:8],
    }
    if not context['completed_checks']:
        context['completed_checks'] = [v for v in context['customer_claims'] if v.get('kind') == 'completed_checks'][-4:]
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
    photos = conversation.photos.order_by('-created_at', '-pk')[:3]
    context['photos'] = [{'id': str(photo.pk), 'status': photo.status,
        'simulated': photo.provider == 'demo',
        'observations': [str(v)[:180] for v in photo.analysis.get('observations', [])[:3]],
        'uncertainties': [str(v)[:180] for v in photo.analysis.get('uncertainties', [])[:2]],
        'connectivity_confirmed': False} for photo in photos]
    context['photo'] = context['photos'][0] if context['photos'] else None
    context['pending_questions'] = context['unresolved_questions']
    context['latest_diagnostic'] = context['diagnostic']
    context['active_ticket'] = context['ticket']
    context['photo_observations'] = context['photos']
    context['equipment_observed'] = context['photo']['observations'] if context['photo'] else []
    # Los mensajes originales permanecen en la BD; el resumen enviado al modelo es acotado.
    for key in ('customer_claims','uncertain_checks','confirmed_completed_checks','customer_reported_checks','asked_questions','answered_questions'):
        while len(json.dumps(context))>7800 and len(context[key])>1:
            context[key]=context[key][1:]
    return context


def remember_claim(context, message, kind):
    context['customer_claims'] = (context['customer_claims'] + [
        {'kind': kind, 'text': message[:300], 'verified': False}])[-8:]
    if kind == 'completed_checks':
        context['completed_checks'] = (context['completed_checks'] + [
            {'text': message[:200], 'verified': False}])[-4:]


def remember_answer(context, message):
    if context['unresolved_questions']:
        question = context['unresolved_questions'].pop(0)
        context['answered_questions'] = (context['answered_questions'] + [
            {'question': question, 'answer': message[:200], 'verified': False}])[-6:]


def remember_equipment(context, message):
    context['equipment_claim'] = {'text': message[:300], 'verified': False}
    if re.search(r'\b[A-Za-z]{1,8}[- ]?\d[A-Za-z0-9-]{2,}\b', message):
        context['answered_questions'] = (context['answered_questions'] + [
            {'question': 'equipment_model', 'answer': message[:200], 'verified': False}])[-6:]
        context['unresolved_questions'] = [v for v in context['unresolved_questions'] if v != 'equipment_model']


def connection_guidance(language):
    return ('Visually check accessible Ethernet plugs for a seated connector and obvious cable damage, then observe the labeled link indicator without unplugging unfamiliar wiring. A connected plug does not prove cable integrity or Internet access.' if language == 'en' else
            'Comprueba visualmente que los conectores Ethernet accesibles estén asentados y sin daños evidentes, y observa el indicador de enlace identificado sin desconectar cables desconocidos. Un conector insertado no prueba integridad del cable ni acceso a Internet.')


def photo_reply(context, language, focus='general', compare=False):
    """Resumen de observaciones guardadas; no compara píxeles ni infiere conectividad."""
    english = language == 'en'
    photos = context.get('photos', [])
    photo = context.get('photo')
    if not photo:
        if focus == 'connections':
            return connection_guidance(language)
        return ('I do not have a photo for this conversation yet. Can you attach a clear equipment photo without private information?' if english else
                'Todavía no tengo una foto de esta conversación. ¿Puedes adjuntar una foto clara del equipo sin información privada?')
    if photo['status'] != 'COMPLETED':
        return ('The latest photo analysis is unavailable, so I cannot judge what it shows. Can you describe the indicator or connection you mean?' if english else
                'El análisis de la última foto no está disponible, así que no puedo valorar su contenido. ¿Puedes describir el indicador o conexión al que te refieres?')
    if photo['simulated'] and all('not interpreted' in v or 'no fue interpretado' in v for v in photo['observations']):
        if compare and len(photos) > 1:
            return ('This is simulated analysis: the photos were not interpreted. I cannot compare the front and back or confirm they show the same device.' if english else
                    'Este análisis es simulado: las fotos no fueron interpretadas. No puedo comparar la parte frontal y trasera ni confirmar que muestren el mismo equipo.')
        text = ('This is simulated analysis: the photo was not interpreted. I can provide general guidance, but cannot verify the visible lights or connections.' if english else
                'Este análisis es simulado: el contenido de la foto no fue interpretado. Puedo orientar de forma general, pero no verificar las luces ni conexiones visibles.')
        return text + (' ' + connection_guidance(language) if focus == 'connections' else '')
    if compare:
        if len(photos) < 2:
            return ('I only have one analyzed view; I cannot compare the front and back yet. Can you send the other view?' if english else
                    'Solo tengo una vista analizada; todavía no puedo comparar la parte frontal y trasera. ¿Puedes enviar la otra vista?')
        current = relevant_observation(photo, focus)
        previous = relevant_observation(photos[1], 'general')
        return ((f'Latest photo: {current} Earlier photo: {previous} ' if english else
                 f'Última foto: {current} Foto anterior: {previous} ') +
                ('These are saved observations, not a fresh image comparison; I cannot confirm both photos show the same device.' if english else
                 'Son observaciones guardadas, no una nueva comparación de imágenes; no puedo confirmar que ambas fotos muestren el mismo equipo.'))
    text = ('I cannot confirm whether this is normal from a photo alone.' if english else
            'No puedo confirmar si esto es normal solo por una foto.')
    if focus == 'indicators':
        text = ('The meaning of this indicator depends on the exact model manual.' if english else
                'El significado de este indicador depende del manual del modelo exacto.')
    if photo['id'] not in context.get('discussed_photo_ids', []):
        text += ' ' + relevant_observation(photo, focus)
        if photo['uncertainties']:
            text += ' ' + photo['uncertainties'][0]
    elif not any(v['question']=='indicator_label' for v in context.get('answered_questions',[])):
        text += ' ' + ('Look at the label beside the light and whether it is steady or blinking; that helps distinguish power from an Ethernet link.' if english else
                       'Observa la etiqueta junto a la luz y si está fija o parpadea; ayuda a distinguir alimentación de enlace Ethernet.')
    if focus == 'connections':
        text += ' ' + connection_guidance(language)
    return text


def relevant_observation(photo, focus):
    terms = {'connections': ('ethernet', 'cable', 'connector', 'port', 'conector', 'puerto'),
             'indicators': ('light', 'led', 'indicator', 'luz', 'luces', 'indicador')}.get(focus, ())
    observations = photo.get('observations', [])
    return next((v for v in observations if any(term in v.lower() for term in terms)),
                observations[0] if observations else '—')


def contextual_reply(intent, context, language, focus='general'):
    """Plantillas seguras: el clasificador no genera instrucciones ni modifica equipos."""
    english = language == 'en'
    texts = {
        'PERSISTING_ISSUE': (
            "Thanks for the update. Your connection problem is still unresolved. Which accessible checks have you completed, or which device do you need help identifying?",
            "Gracias por avisar. Tu problema de conexión sigue sin resolverse. ¿Qué comprobaciones accesibles completaste o qué equipo necesitas identificar?"),
        'EQUIPMENT_CLARIFICATION': (
            "Thanks for clarifying which equipment you have. A router or modem is different from a PoE injector or outdoor CPE; its identity is still unverified. What exact model is on its label (without serial numbers or passwords)?",
            "Gracias por aclarar qué equipo tienes. Un router o módem es distinto de un inyector PoE o una CPE exterior; su identidad sigue sin verificar. ¿Qué modelo figura en la etiqueta (sin números de serie ni contraseñas)?"),
        'REPORT_INDICATORS': (
            "Local router indicators do not prove outdoor CPE connectivity; their meaning depends on the model. Which labeled indicator is green?",
            "Los indicadores locales del router no prueban conectividad de la CPE exterior; su significado depende del modelo. ¿Qué indicador está verde?"),
        'CLARIFY_COMPLETED_CHECKS': (
            "I understand you already tried the previous suggestion. Which accessible checks did you complete? I will record them as your report, not as verified connectivity.",
            "Entiendo que ya intentaste la sugerencia anterior. ¿Qué comprobaciones accesibles realizaste? Las registraré como tu declaración, no como conectividad verificada."),
        'EXPLAIN_POE': (
            "A PoE injector is a separate adapter that can power compatible equipment through Ethernet; your router may be a different device. Do not disconnect unfamiliar cables. Can you share a photo of the separate adapter without private information?",
            "Un inyector PoE es un adaptador separado que puede alimentar equipos compatibles mediante Ethernet; tu router puede ser otro dispositivo. No desconectes cables desconocidos. ¿Puedes enviar una foto del adaptador separado sin información privada?"),
        'REQUEST_PHOTO': (
            "Yes, use Attach photo to send JPEG or PNG, or WebP (up to 5 MiB). Avoid passwords, QR codes and personal information.",
            "Sí, usa Attach photo para enviar JPEG o PNG, o WebP (hasta 5 MiB). Evita contraseñas, códigos QR y datos personales."),
        'PHOTO_QUESTION': (
            "The meaning of a light depends on the device model and its label. Which indicator do you mean, and is it steady or blinking? A photo alone cannot confirm connectivity or equipment identity.",
            "El significado de una luz depende del modelo y su etiqueta. ¿A qué indicador te refieres y está fijo o parpadeando? Una foto por sí sola no confirma conectividad ni identidad del equipo."),
        'OTHER': (
            "We are still working on your reported connection problem. Are you describing the photographed equipment, an indicator, or checks you completed?",
            "Seguimos trabajando en tu problema de conexión. ¿Te refieres al equipo fotografiado, a un indicador o a las comprobaciones que realizaste?"),
    }
    text = texts.get(intent, texts['OTHER'])[0 if english else 1]
    if intent in {'PHOTO_QUESTION', 'PHOTO_COMPARISON'}:
        text = photo_reply(context, language, focus, compare=intent == 'PHOTO_COMPARISON')
    if intent == 'ANSWER_CLARIFICATION':
        text = ('Thanks, I have recorded that clarification as your report.' if english else
                'Gracias, registré esa aclaración como tu declaración.')
    if intent == 'EQUIPMENT_CLARIFICATION' and any(v['question'] == 'equipment_model' for v in context['answered_questions']):
        text = ('Thanks, I have retained your equipment clarification. We can continue general Ethernet checks without its exact model.' if english else
                'Gracias, conservo tu aclaración del equipo. Podemos continuar las comprobaciones generales sin el modelo exacto.')
    elif intent == 'EQUIPMENT_CLARIFICATION' and context.get('equipment_claim'):
        text = ('Thanks, I have retained your equipment identification. A router is different from a PoE injector. We can continue general Ethernet checks without its exact model.' if english else
                'Gracias, conservo tu identificación del equipo. Un router es distinto de un inyector PoE. Podemos continuar las comprobaciones generales de Ethernet sin el modelo exacto.')
    if intent == 'REPORT_INDICATORS' and any(v['question'] == 'indicator_label' for v in context['answered_questions']):
        text = ('I have retained your indicator report; local router lights do not prove outdoor CPE connectivity.' if english else
                'Conservo tu informe del indicador; las luces locales del router no prueban conectividad de la CPE exterior.')
    if intent == 'PERSISTING_ISSUE' and context.get('ticket'):
        text = ('Your connection problem remains recorded for technical review. You do not need to repeat the same checks now.' if english else
                'Tu problema de conexión sigue registrado para revisión técnica. No necesitas repetir las mismas comprobaciones ahora.')
    supplied=context.get('current_supplied_evidence',[])
    if supplied and intent in {'PHOTO_QUESTION','OTHER'}:
        labels={'cable_path':('cable routing','recorrido de cables'),'ports':('ports','puertos'),
            'power':('power','alimentación'),'indicators':('indicators','indicadores'),
            'equipment_role':('equipment roles','función de los equipos')}
        facts=', '.join(labels[key][0 if english else 1] for key in supplied)
        text=(f'I have retained your reports about {facts}; they are not independently verified.' if english else
              f'Conservo tus declaraciones sobre {facts}; no están verificadas independientemente.')
    diagnostic = context.get('diagnostic')
    if diagnostic and diagnostic['result_code'] == 'CPE_UNREACHABLE':
        if diagnostic['source'] == 'simulation':
            text += ' ' + ('The latest simulated check still cannot reach the outdoor equipment; the cause is unconfirmed.' if english else 'La última comprobación simulada sigue sin alcanzar el equipo exterior; la causa no está confirmada.')
    if context.get('ticket'):
        ticket = context['ticket']
        text += f" {'Ticket' if english else 'Ticket'} {ticket['number']}: {ticket['status']}."
    return text
