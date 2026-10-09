"""Orquestación y persistencia de diagnósticos exclusivamente simulados."""

import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from customers.models import InternetService
from tickets.services import create_ticket, record_ticket_action
from .engine import administrative_assessment, evaluate
from .models import DiagnosticRun, SimulationState
from .simulation import NetworkMetrics, Scenario, simulate


@transaction.atomic
def run_diagnostic(*, internet_service, conversation=None) -> DiagnosticRun:
    service = InternetService.objects.select_for_update().get(pk=internet_service.pk)
    try:
        state = SimulationState.objects.get(internet_service=service)
    except SimulationState.DoesNotExist as error:
        raise ValidationError("Service is not enrolled in the demo simulator.") from error
    started_at = timezone.now()
    assessment = administrative_assessment(service.status)
    try:
        scenario = Scenario(state.scenario)
    except ValueError as error:
        raise ValidationError("Unknown stored simulation scenario.") from error
    if assessment is not None:
        metrics = NetworkMetrics()
        if service.status == InternetService.Status.SUSPENDED:
            scenario = Scenario.ADMIN_SUSPENDED
    else:
        if scenario == Scenario.ADMIN_SUSPENDED:
            raise ValidationError("Active service cannot use ADMIN_SUSPENDED; select a technical scenario.")
        metrics = simulate(scenario, service.advertised_download_mbps)
        assessment = evaluate(metrics, service.advertised_download_mbps)
    return DiagnosticRun.objects.create(
        internet_service=service, conversation=conversation, scenario=scenario,
        result=assessment.result, result_code=assessment.code, assessment=assessment.to_dict(),
        metrics=metrics.to_dict(), source=DiagnosticRun.Source.SIMULATION,
        started_at=started_at, completed_at=timezone.now(),
    )


@transaction.atomic
def set_demo_scenario(*, internet_service, scenario: str) -> SimulationState:
    service = InternetService.objects.select_for_update().get(pk=internet_service.pk)
    try:
        scenario = Scenario(scenario)
    except ValueError as error:
        raise ValidationError("Unknown simulation scenario.") from error
    try:
        state = SimulationState.objects.get(internet_service=service)
    except SimulationState.DoesNotExist as error:
        raise ValidationError("Service is not enrolled in the demo simulator.") from error
    if scenario == Scenario.ADMIN_SUSPENDED and service.status != InternetService.Status.SUSPENDED:
        raise ValidationError("ADMIN_SUSPENDED requires administrative suspension.")
    state.scenario = scenario
    state.full_clean()
    state.save(update_fields=["scenario", "updated_at"])
    return state


def escalation_payload(run: DiagnosticRun) -> dict | None:
    if run.source != DiagnosticRun.Source.SIMULATION or not run.assessment.get("requires_escalation"):
        return None
    return {
        "customer_id": str(run.internet_service.customer_id),
        "service_id": run.internet_service_id,
        "diagnostic_run_id": run.pk,
        "result_code": run.result_code,
        "summary": run.assessment["summary"],
        "metrics": run.metrics,
        "recommended_actions": run.assessment["recommended_actions"],
        "suggested_priority": run.assessment["suggested_priority"],
    }


@transaction.atomic
def escalate_diagnostic(*, run: DiagnosticRun, user=None, reported_actions=()):
    payload = escalation_payload(run)
    if payload is None:
        return None
    if run.conversation_id is None:
        raise ValidationError("A conversation is required for duplicate-safe escalation.")
    payload["reported_actions"] = list(reported_actions)
    ticket = create_ticket(
        customer=run.internet_service.customer, internet_service=run.internet_service,
        conversation=run.conversation,
        incident_key=f"diagnostic-{run.internet_service_id}-{run.result_code.lower()}",
        title=payload["summary"], description=json.dumps(payload, ensure_ascii=False, indent=2),
        priority=payload["suggested_priority"], user=user,
    )
    if payload["reported_actions"]:
        record_ticket_action(
            ticket=ticket, user=user,
            description="Customer-reported actions: " + " ".join(payload["reported_actions"]),
        )
    return ticket
