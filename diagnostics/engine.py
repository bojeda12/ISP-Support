"""Reglas puras: no consultan hardware, ORM ni el simulador."""

from dataclasses import asdict, dataclass

from . import thresholds
from .simulation import NetworkMetrics


@dataclass(frozen=True)
class Assessment:
    code: str
    result: str
    summary: str
    findings: list[str]
    recommended_actions: list[str]
    follow_up: str
    requires_escalation: bool = False
    suggested_priority: str | None = None

    def to_dict(self):
        return asdict(self)


def administrative_assessment(status: str) -> Assessment | None:
    if status == "ACTIVE":
        return None
    if status == "SUSPENDED":
        return Assessment(
            "SERVICE_SUSPENDED", "UNKNOWN", "Servicio suspendido administrativamente.",
            ["No se consultaron métricas técnicas."],
            ["Consultar con administración el motivo y los pasos de reactivación."],
            "CONTACT_ADMINISTRATION",
        )
    return Assessment(
        "SERVICE_INACTIVE", "UNKNOWN", "Servicio no activo administrativamente.",
        ["No se consultaron métricas técnicas."],
        ["Revisar el estado del contrato con administración."], "CONTACT_ADMINISTRATION",
    )


def evaluate(metrics: NetworkMetrics, advertised_download_mbps: int) -> Assessment:
    if metrics.cpe_online is False:
        return Assessment(
            "CPE_UNREACHABLE", "FAILED", "La CPE no responde en la simulación.",
            ["No hay mediciones disponibles de la CPE; la causa no está confirmada."],
            ["Comprobar alimentación e indicadores del adaptador PoE y revisar cables y conectores accesibles.",
             "El PoE es una posible causa; no manipular instalaciones eléctricas ni subir a la antena.",
             "Tras la comprobación, repetir el diagnóstico; si persiste, escalar a soporte técnico."],
            "CHECK_PHYSICAL_CONNECTIONS_AND_RETEST", True, "HIGH",
        )
    if metrics.cpe_online is None:
        return Assessment("INSUFFICIENT_DATA", "UNKNOWN", "No hay datos suficientes.", [],
                          ["Repetir el diagnóstico."], "RETEST")
    signal_findings = []
    if metrics.rssi_dbm is not None and metrics.rssi_dbm < thresholds.MIN_RSSI_DBM:
        signal_findings.append("RSSI inferior al umbral de simulación.")
    if metrics.snr_db is not None and metrics.snr_db < thresholds.MIN_SNR_DB:
        signal_findings.append("SNR inferior al umbral de simulación.")
    if signal_findings:
        return Assessment(
            "SIGNAL_DEGRADED", "DEGRADED", "Señal inalámbrica degradada.", signal_findings,
            ["Revisar visualmente obstáculos y cables accesibles sin mover la antena.",
             "Solicitar revisión técnica del enlace y repetir las mediciones."],
            "TECHNICAL_REVIEW", True, "MEDIUM",
        )
    findings = []
    if (metrics.download_mbps is not None and
            metrics.download_mbps < advertised_download_mbps * thresholds.MIN_DOWNLOAD_RATIO):
        findings.append("Descarga inferior a la proporción esperada en la simulación.")
    if metrics.latency_ms is not None and metrics.latency_ms > thresholds.MAX_LATENCY_MS:
        findings.append("Latencia superior al umbral de simulación.")
    if (metrics.packet_loss_percent is not None and
            metrics.packet_loss_percent > thresholds.MAX_PACKET_LOSS_PERCENT):
        findings.append("Pérdida de paquetes superior al umbral de simulación.")
    if findings:
        return Assessment(
            "PERFORMANCE_DEGRADED", "DEGRADED", "Rendimiento degradado.", findings,
            ["Revisar cables accesibles y repetir una prueba por cable sin descargas simultáneas.",
             "Si persiste, solicitar revisión técnica de capacidad y enlace."],
            "TECHNICAL_REVIEW", True, "MEDIUM",
        )
    if any(value is None for value in (
        metrics.rssi_dbm, metrics.snr_db, metrics.latency_ms,
        metrics.packet_loss_percent, metrics.download_mbps,
    )):
        return Assessment("INSUFFICIENT_DATA", "UNKNOWN", "Mediciones incompletas.", [],
                          ["Repetir el diagnóstico."], "RETEST")
    return Assessment(
        "NO_FAULT_DETECTED", "PASSED", "No se detecta falla en las métricas simuladas.",
        ["Las mediciones están dentro de los umbrales de la demo."],
        ["Confirmar con el cliente si el síntoma desapareció."], "CONFIRM_WITH_CUSTOMER",
    )
