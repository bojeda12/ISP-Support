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
            "SERVICE_SUSPENDED", "UNKNOWN", "Service is administratively suspended.",
            ["No technical measurements were requested."],
            ["Contact administration about the suspension and reactivation process."],
            "CONTACT_ADMINISTRATION",
        )
    return Assessment(
        "SERVICE_INACTIVE", "UNKNOWN", "Service is administratively inactive.",
        ["No technical measurements were requested."],
        ["Review the contract status with administration."], "CONTACT_ADMINISTRATION",
    )


def evaluate(metrics: NetworkMetrics, advertised_download_mbps: int) -> Assessment:
    if metrics.cpe_online is False:
        return Assessment(
            "CPE_UNREACHABLE", "FAILED", "The CPE is not responding in the simulation.",
            ["CPE measurements are unavailable; the cause is unconfirmed."],
            ["Observe PoE power indicators if present and inspect accessible cables and connectors.",
             "PoE is one possible cause; do not handle electrical wiring or climb to the antenna.",
             "Repeat the diagnostic after the checks; escalate to technical support if the issue persists."],
            "CHECK_PHYSICAL_CONNECTIONS_AND_RETEST", True, "HIGH",
        )
    if metrics.cpe_online is None:
        return Assessment("INSUFFICIENT_DATA", "UNKNOWN", "Insufficient data.", [],
                          ["Repeat the diagnostic."], "RETEST")
    signal_findings = []
    if metrics.rssi_dbm is not None and metrics.rssi_dbm < thresholds.MIN_RSSI_DBM:
        signal_findings.append("RSSI is below the simulation threshold.")
    if metrics.snr_db is not None and metrics.snr_db < thresholds.MIN_SNR_DB:
        signal_findings.append("SNR is below the simulation threshold.")
    if signal_findings:
        return Assessment(
            "SIGNAL_DEGRADED", "DEGRADED", "Wireless signal is degraded.", signal_findings,
            ["Visually inspect obstructions and accessible cables without moving the antenna.",
             "Request technical link review and repeat measurements."],
            "TECHNICAL_REVIEW", True, "MEDIUM",
        )
    findings = []
    if (metrics.download_mbps is not None and
            metrics.download_mbps < advertised_download_mbps * thresholds.MIN_DOWNLOAD_RATIO):
        findings.append("Download speed is below the expected simulation ratio.")
    if metrics.latency_ms is not None and metrics.latency_ms > thresholds.MAX_LATENCY_MS:
        findings.append("Latency exceeds the simulation threshold.")
    if (metrics.packet_loss_percent is not None and
            metrics.packet_loss_percent > thresholds.MAX_PACKET_LOSS_PERCENT):
        findings.append("Packet loss exceeds the simulation threshold.")
    if findings:
        return Assessment(
            "PERFORMANCE_DEGRADED", "DEGRADED", "Performance is degraded.", findings,
            ["Inspect accessible cables and repeat a wired test without concurrent downloads.",
             "If the issue persists, request technical capacity and link review."],
            "TECHNICAL_REVIEW", True, "MEDIUM",
        )
    if any(value is None for value in (
        metrics.rssi_dbm, metrics.snr_db, metrics.latency_ms,
        metrics.packet_loss_percent, metrics.download_mbps,
    )):
        return Assessment("INSUFFICIENT_DATA", "UNKNOWN", "Measurements are incomplete.", [],
                          ["Repeat the diagnostic."], "RETEST")
    return Assessment(
        "NO_FAULT_DETECTED", "PASSED", "No fault detected in simulated measurements.",
        ["Measurements are within demo thresholds."],
        ["Ask the customer whether the symptom has disappeared."], "CONFIRM_WITH_CUSTOMER",
    )
