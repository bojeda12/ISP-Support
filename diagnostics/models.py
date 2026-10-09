from django.core.exceptions import ValidationError
from django.db import models

from .simulation import Scenario


class SimulationState(models.Model):
    internet_service = models.OneToOneField(
        "customers.InternetService", on_delete=models.CASCADE, related_name="simulation_state"
    )
    scenario = models.CharField(max_length=20, choices=Scenario)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.internet_service}: {self.scenario}"


class DiagnosticRun(models.Model):
    class Source(models.TextChoices):
        SIMULATION = "simulation", "Simulación"
        EXTERNAL = "external", "Externo"

    class Result(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Desconocido"
        PASSED = "PASSED", "Correcto"
        FAILED = "FAILED", "Fallo"
        DEGRADED = "DEGRADED", "Degradado"

    internet_service = models.ForeignKey(
        "customers.InternetService", on_delete=models.PROTECT, related_name="diagnostic_runs"
    )
    conversation = models.ForeignKey(
        "conversations.Conversation", on_delete=models.PROTECT,
        related_name="diagnostic_runs", null=True, blank=True
    )
    scenario = models.CharField(max_length=100)
    result = models.CharField(max_length=12, choices=Result, default=Result.UNKNOWN)
    result_code = models.CharField(max_length=32, blank=True)
    assessment = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=10, choices=Source, default=Source.SIMULATION)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [("run_simulated_diagnostic", "Puede ejecutar diagnósticos simulados internos")]

    def clean(self):
        super().clean()
        if self.conversation_id:
            conversation = self.conversation
            if (conversation.customer_id != self.internet_service.customer_id or
                    conversation.internet_service_id not in (None, self.internet_service_id)):
                raise ValidationError({"conversation": "Conversation must match the service and customer."})
        if self.completed_at and (not self.started_at or self.completed_at < self.started_at):
            raise ValidationError({"completed_at": "Completion requires an earlier start."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.scenario} ({self.result})"
