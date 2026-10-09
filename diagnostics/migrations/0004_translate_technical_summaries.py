"""Translate known generated technical text; never rewrite customer messages."""
import json
from django.db import migrations

TRANSLATIONS = {'Comprobar alimentación e indicadores del adaptador PoE y revisar cables y conectores accesibles.': 'Observe '
                                                                                                     'PoE '
                                                                                                     'power '
                                                                                                     'indicators '
                                                                                                     'if '
                                                                                                     'present '
                                                                                                     'and '
                                                                                                     'inspect '
                                                                                                     'accessible '
                                                                                                     'cables '
                                                                                                     'and '
                                                                                                     'connectors.',
 'Confirmar con el cliente si el síntoma desapareció.': 'Ask the customer whether the symptom has '
                                                        'disappeared.',
 'Consultar con administración el motivo y los pasos de reactivación.': 'Contact administration '
                                                                        'about the suspension and '
                                                                        'reactivation process.',
 'Descarga inferior a la proporción esperada en la simulación.': 'Download speed is below the '
                                                                 'expected simulation ratio.',
 'El PoE es una posible causa; no manipular instalaciones eléctricas ni subir a la antena.': 'PoE '
                                                                                             'is '
                                                                                             'one '
                                                                                             'possible '
                                                                                             'cause; '
                                                                                             'do '
                                                                                             'not '
                                                                                             'handle '
                                                                                             'electrical '
                                                                                             'wiring '
                                                                                             'or '
                                                                                             'climb '
                                                                                             'to '
                                                                                             'the '
                                                                                             'antenna.',
 'La CPE no responde en la simulación.': 'The CPE is not responding in the simulation.',
 'Las mediciones están dentro de los umbrales de la demo.': 'Measurements are within demo '
                                                            'thresholds.',
 'Latencia superior al umbral de simulación.': 'Latency exceeds the simulation threshold.',
 'Mediciones incompletas.': 'Measurements are incomplete.',
 'No hay datos suficientes.': 'Insufficient data.',
 'No hay mediciones disponibles de la CPE; la causa no está confirmada.': 'CPE measurements are '
                                                                          'unavailable; the cause '
                                                                          'is unconfirmed.',
 'No se consultaron métricas técnicas.': 'No technical measurements were requested.',
 'No se detecta falla en las métricas simuladas.': 'No fault detected in simulated measurements.',
 'Pérdida de paquetes superior al umbral de simulación.': 'Packet loss exceeds the simulation '
                                                          'threshold.',
 'RSSI inferior al umbral de simulación.': 'RSSI is below the simulation threshold.',
 'Rendimiento degradado.': 'Performance is degraded.',
 'Repetir el diagnóstico.': 'Repeat the diagnostic.',
 'Revisar cables accesibles y repetir una prueba por cable sin descargas simultáneas.': 'Inspect '
                                                                                        'accessible '
                                                                                        'cables '
                                                                                        'and '
                                                                                        'repeat a '
                                                                                        'wired '
                                                                                        'test '
                                                                                        'without '
                                                                                        'concurrent '
                                                                                        'downloads.',
 'Revisar el estado del contrato con administración.': 'Review the contract status with '
                                                       'administration.',
 'Revisar visualmente obstáculos y cables accesibles sin mover la antena.': 'Visually inspect '
                                                                            'obstructions and '
                                                                            'accessible cables '
                                                                            'without moving the '
                                                                            'antenna.',
 'SNR inferior al umbral de simulación.': 'SNR is below the simulation threshold.',
 'Servicio no activo administrativamente.': 'Service is administratively inactive.',
 'Servicio suspendido administrativamente.': 'Service is administratively suspended.',
 'Señal inalámbrica degradada.': 'Wireless signal is degraded.',
 'Si persiste, solicitar revisión técnica de capacidad y enlace.': 'If the issue persists, request '
                                                                   'technical capacity and link '
                                                                   'review.',
 'Solicitar revisión técnica del enlace y repetir las mediciones.': 'Request technical link review '
                                                                    'and repeat measurements.',
 'Tras la comprobación, repetir el diagnóstico; si persiste, escalar a soporte técnico.': 'Repeat '
                                                                                          'the '
                                                                                          'diagnostic '
                                                                                          'after '
                                                                                          'the '
                                                                                          'checks; '
                                                                                          'escalate '
                                                                                          'to '
                                                                                          'technical '
                                                                                          'support '
                                                                                          'if the '
                                                                                          'issue '
                                                                                          'persists.'}


def translate(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [translate(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: translate(item, mapping) for key, item in value.items()}
    return value


def convert(apps, schema_editor, mapping):
    alias = schema_editor.connection.alias
    DiagnosticRun = apps.get_model("diagnostics", "DiagnosticRun")
    Ticket = apps.get_model("tickets", "Ticket")
    for run in DiagnosticRun.objects.using(alias).filter(source="simulation").iterator():
        assessment = translate(run.assessment, mapping)
        if assessment != run.assessment:
            DiagnosticRun.objects.using(alias).filter(pk=run.pk).update(assessment=assessment)
    for ticket in Ticket.objects.using(alias).filter(incident_key__startswith="diagnostic-").iterator():
        title = mapping.get(ticket.title, ticket.title)
        description = ticket.description
        try:
            payload = json.loads(description)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict) and payload.get("summary") in mapping:
            description = json.dumps(translate(payload, mapping), ensure_ascii=False, indent=2)
        if title != ticket.title or description != ticket.description:
            Ticket.objects.using(alias).filter(pk=ticket.pk).update(title=title, description=description)


def forwards(apps, schema_editor):
    convert(apps, schema_editor, TRANSLATIONS)


def backwards(apps, schema_editor):
    convert(apps, schema_editor, {value: key for key, value in TRANSLATIONS.items()})


class Migration(migrations.Migration):
    dependencies = [("diagnostics", "0003_alter_diagnosticrun_options_and_more"),
                    ("tickets", "0002_alter_ticket_priority_alter_ticket_status_and_more")]
    operations = [migrations.RunPython(forwards, backwards)]
