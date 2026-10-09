"""Simulador determinista aislado: no contiene operaciones de red."""

from dataclasses import asdict, dataclass

from django.db import models


class Scenario(models.TextChoices):
    HEALTHY = "HEALTHY", "Conexión normal"
    CPE_OFFLINE = "CPE_OFFLINE", "CPE sin respuesta"
    WEAK_SIGNAL = "WEAK_SIGNAL", "Señal débil"
    LOW_THROUGHPUT = "LOW_THROUGHPUT", "Rendimiento bajo"
    ADMIN_SUSPENDED = "ADMIN_SUSPENDED", "Suspensión administrativa"


@dataclass(frozen=True)
class NetworkMetrics:
    cpe_online: bool | None = None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    latency_ms: float | None = None
    packet_loss_percent: float | None = None
    download_mbps: float | None = None
    ap_identifier: str | None = None

    def to_dict(self):
        return asdict(self)


def simulate(scenario: str, advertised_download_mbps: int) -> NetworkMetrics:
    scenario = Scenario(scenario)
    if scenario == Scenario.ADMIN_SUSPENDED:
        return NetworkMetrics()
    if scenario == Scenario.CPE_OFFLINE:
        return NetworkMetrics(cpe_online=False)
    if scenario == Scenario.WEAK_SIGNAL:
        return NetworkMetrics(True, -82, 9, 85, 6, round(advertised_download_mbps * .25, 2), "DEMO-AP-01")
    if scenario == Scenario.LOW_THROUGHPUT:
        return NetworkMetrics(True, -58, 30, 60, 2, round(advertised_download_mbps * .2, 2), "DEMO-AP-01")
    return NetworkMetrics(True, -58, 30, 12, 0, round(advertised_download_mbps * .95, 2), "DEMO-AP-01")
