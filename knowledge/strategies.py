"""Taxonomía configurable; describe capacidades, no prescribe un diálogo rígido."""
from .models import TroubleshootingCategory


def investigation_strategy(category, language):
    row=TroubleshootingCategory.objects.filter(code=category,active=True).first()
    if not row:
        return None
    checks=row.safe_checks
    return {'category':row.code,'relevant_evidence':row.relevant_evidence,
        'available_tools':row.available_tools,
        'safe_checks':checks.get(language,[]) if isinstance(checks,dict) else checks,
        'documentation_requirements':row.documentation_requirements,
        'escalation_criteria':row.escalation_criteria,'knowledge_sources':row.knowledge_sources,
        'measurement_policy':'Only actual authorized simulator results are measurements; other capabilities are unavailable.'}
