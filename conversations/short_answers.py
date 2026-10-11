"""Orientación breve sin inventar observaciones ni acciones de red."""
import re
from .ai import Interpretation, Intent, normalize
from .context import relevant_observation


def short_interpretation(message, language):
    text = normalize(message).strip(' ?.¿!')
    if re.fullmatch(r'is (it|this|that) (good|ok|okay|normal)|esta (bien|normal)', text):
        return Interpretation(intent=Intent.PHOTO_QUESTION, language=language, photo_focus='connections')
    if re.search(r'\b(wire|cable|led|light|luz|luces)\b', text) and re.search(r'\b(green|orange|verde|naranja|amber|ambar)\b', text):
        return Interpretation(intent=Intent.REPORT_INDICATORS, language=language, photo_focus='indicators')
    if re.fullmatch(r'is this (device|a router|a modem)|what (is this|device is this)|que (equipo|dispositivo) es', text):
        return Interpretation(intent=Intent.EQUIPMENT_CLARIFICATION, language=language)
    return None


def short_answer(message, context, language, intent):
    if short_interpretation(message, language) is None:
        return None
    en = language == 'en'
    photo = context.get('photo')
    real = photo and photo['status'] == 'COMPLETED' and bool(photo['observations']) and not all('not interpreted' in v or 'no fue interpretado' in v for v in photo['observations'])
    if intent == Intent.REPORT_INDICATORS:
        text = ('If you mean the green/orange lights beside the yellow Ethernet cable, they may indicate a physical link, activity or negotiated speed; the exact meaning varies by model. They do not prove Internet access.' if en else
                'Si te refieres a las luces verde/naranja junto al cable Ethernet amarillo, pueden indicar enlace físico, actividad o velocidad negociada; depende del modelo. No prueban acceso a Internet.')
        question = 'Is the light beside a LAN or WAN label?' if en else '¿La luz está junto a una etiqueta LAN o WAN?'
    elif intent == Intent.EQUIPMENT_CLARIFICATION:
        observation = relevant_observation(photo, 'general') if real else ''
        text = ((f'The photo analysis reports: {observation} ' if en else f'El análisis de la foto indica: {observation} ') if observation else
                ('Demo mode cannot identify this device from pixels. ' if photo and photo['simulated'] and en else
                 'La demo no identifica este dispositivo a partir de píxeles. ' if photo and photo['simulated'] else ''))
        text += ('A router/modem/gateway serves a different role from a separate PoE injector, so we should identify it before applying the PoE guide.' if en else
                 'Un router/módem/gateway cumple una función distinta de un inyector PoE separado; conviene identificarlo antes de aplicar la guía PoE.')
        question = ('Is this the indoor router rather than a separate PoE adapter?' if en else '¿Es el router interior en lugar de un adaptador PoE separado?') if not context.get('equipment_claim') else ('We can continue general Ethernet checks without its exact model.' if en else 'Podemos continuar las comprobaciones generales de Ethernet sin el modelo exacto.')
    else:
        text = ((f'The photo analysis reports: {relevant_observation(photo, "connections")} ' if en else
                 f'El análisis de la foto indica: {relevant_observation(photo, "connections")} ') if real else
                 ('The latest photo analysis is unavailable. ' if photo and photo['status'] != 'COMPLETED' and en else
                  'El análisis de la última foto no está disponible. ' if photo and photo['status'] != 'COMPLETED' else
                  'This demo has not interpreted the photo. ' if photo and photo['simulated'] and en else
                 'Esta demo no ha interpretado la foto. ' if photo and photo['simulated'] else
                 'I cannot assess the photo content right now. ' if en else 'Ahora no puedo valorar el contenido de la foto. '))
        text += ('I cannot confirm whether this is normal from a photo alone. A seated cable or lit link indicator can suggest a local physical connection, but cannot confirm the correct port or Internet access.' if en else
                 'No puedo confirmar si es normal solo por una foto. Un cable asentado o una luz de enlace pueden sugerir conexión física local, pero no confirman el puerto correcto ni acceso a Internet.')
        question = 'What label is printed beside that port?' if en else '¿Qué etiqueta figura junto a ese puerto?'
    if (context.get('diagnostic') or {}).get('result_code') == 'CPE_UNREACHABLE':
        text += ' ' + ('The latest simulated check still cannot reach the outdoor equipment.' if en else 'La última comprobación simulada sigue sin alcanzar el equipo exterior.')
    if any(item['question']=='indicator_label' for item in context.get('answered_questions',[])) and intent in {Intent.PHOTO_QUESTION,Intent.REPORT_INDICATORS}:
        question=''
    return (text + ' ' + question).strip()
