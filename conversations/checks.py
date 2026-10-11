from django.core.checks import Error, register
from .instructions import catalog_errors


@register()
def instruction_catalog_check(app_configs, **kwargs):
    try:
        return [Error(error, id='conversations.E001') for error in catalog_errors()]
    except (KeyError, ValueError):
        return [Error('Instruction catalog is incomplete; legacy fallback is forbidden.', id='conversations.E002')]
