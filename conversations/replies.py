"""Respuestas bilingües controladas; no se muestra texto libre generado por la IA."""


TEXT = {
    "greeting": (
        "Hola. Puedo revisar el estado de tu servicio, problemas de conexión y tickets de esta conversación.",
        "Hello. I can check your service, connection problems and tickets in this conversation.",
    ),
    "other": ("Describe si no tienes Internet, está lento o quieres consultar el estado de tu servicio o ticket.",
              "Tell me whether you have no Internet, a slow connection, or want to check your service or ticket."),
    "unavailable": ("No pude interpretar tu mensaje en este momento. Lo he guardado; vuelve a intentarlo. No se realizaron cambios en tu servicio ni tickets.",
                    "I could not interpret your message right now. It has been saved; please try again. Your service and tickets were not changed."),
    "diagnostic_unavailable": ("Guardé tu mensaje, pero no pude completar el diagnóstico simulado. Solicita revisión al operador de la demo.",
                               "Your message was saved, but the simulated diagnostic could not be completed. Please ask the demo operator to review it."),
    "no_previous_check": ("Primero describe el problema para comprobar si corresponde revisar las conexiones físicas.",
                          "Please describe the problem first so we can determine whether physical connection checks are appropriate."),
    "no_ticket": ("No hay tickets asociados a esta conversación.", "There are no tickets associated with this conversation."),
    "ticket_status": ("Ticket {number}: {status}.", "Ticket {number}: {status}."),
    "ticket_created": ("Tu incidencia está registrada con el ticket {number}. No hay visita ni reparación confirmada.",
                       "Your issue is recorded under ticket {number}. No visit or repair has been confirmed."),
    "service_status": ("Estado administrativo del servicio: {status}. Este dato no confirma la conectividad técnica.",
                       "Administrative service status: {status}. This does not confirm technical connectivity."),
    "SERVICE_SUSPENDED": (
        "Tu servicio está suspendido administrativamente. Contacta con administración para conocer los pasos de reactivación. No se ejecutaron mediciones técnicas.",
        "Your service is administratively suspended. Contact administration for reactivation steps. No technical measurements were performed.",
    ),
    "SERVICE_INACTIVE": (
        "Tu servicio no está activo administrativamente. Contacta con administración. No se ejecutaron mediciones técnicas.",
        "Your service is not administratively active. Contact administration. No technical measurements were performed.",
    ),
    "CPE_UNREACHABLE": (
        "La CPE no responde en la simulación; la causa no está confirmada. Comprueba la alimentación y los indicadores del inyector PoE y los cables y conectores accesibles. El PoE es solo una posible causa. No subas al techo ni manipules instalaciones eléctricas. Avísame cuando hayas realizado las comprobaciones para repetir el diagnóstico.",
        "The CPE is not responding in the simulation; the cause is unconfirmed. Check the PoE injector power and indicators and safely accessible cables and connectors. PoE is only one possible cause. Do not climb onto the roof or handle electrical wiring. Tell me when you have completed the checks so I can run the diagnostic again.",
    ),
    "CPE_ESCALATED": (
        "Gracias por realizar esas comprobaciones accesibles. El nuevo diagnóstico simulado sigue sin obtener respuesta de la CPE. La incidencia queda escalada para revisión técnica; no necesitas repetir ahora las mismas comprobaciones.",
        "Thank you for completing those accessible checks. The new simulated diagnostic still receives no response from the CPE. The issue has been escalated for technical review; you do not need to repeat the same checks now.",
    ),
    "CPE_FOLLOW_UP": (
        "El diagnóstico simulado sigue sin respuesta de la CPE. Esto no confirma la causa ni requiere repetir las mismas instrucciones.",
        "The simulated diagnostic still receives no response from the CPE. This does not confirm the cause or require repeating the same instructions.",
    ),
    "SIGNAL_DEGRADED": (
        "Las mediciones simuladas indican señal débil. Revisa visualmente obstáculos y cables accesibles sin mover la antena ni subir al techo. Se requiere revisión técnica del enlace.",
        "Simulated measurements indicate a weak signal. Visually check obstacles and accessible cables without moving the antenna or climbing onto the roof. The link needs technical review.",
    ),
    "PERFORMANCE_DEGRADED": (
        "Las mediciones simuladas indican rendimiento bajo. Revisa cables accesibles y prueba por cable sin descargas simultáneas. Se requiere revisión técnica si persiste.",
        "Simulated measurements indicate low performance. Check accessible cables and test over a cable without simultaneous downloads. Technical review is needed if the problem persists.",
    ),
    "NO_FAULT_DETECTED": (
        "Las nuevas métricas simuladas no muestran falla de conectividad. Confirma si puedes navegar; esto no demuestra una reparación en equipos reales.",
        "The new simulated metrics show no connectivity fault. Please confirm whether you can browse; this does not prove a repair on real equipment.",
    ),
    "INSUFFICIENT_DATA": ("No hay mediciones suficientes para confirmar el estado. Repite el diagnóstico.",
                          "There are not enough measurements to confirm the status. Please repeat the diagnostic."),
}


def reply(key: str, language: str, **values) -> str:
    return TEXT[key][1 if language == "en" else 0].format(**values)


def diagnostic_payload(run, language: str, display_key=None) -> dict:
    # Exponer solo métricas útiles al cliente: el identificador interno del AP no sale al chat.
    metrics = {key: value for key, value in run.metrics.items() if key != "ap_identifier"}
    return {
        "id": run.pk, "result_code": run.result_code, "result": run.result,
        "source": run.source, "metrics": metrics,
        "explanation": reply(display_key or run.result_code, language),
    }
