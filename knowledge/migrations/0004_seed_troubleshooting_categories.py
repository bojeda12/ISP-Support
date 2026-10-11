from django.db import migrations


def seed(apps,schema_editor):
    Category=apps.get_model('knowledge','TroubleshootingCategory')
    rows={
        'NO_INTERNET':(['cable_path','power','indicators','cpe_reachability'],['simulated_connectivity'],
            ['Visually inspect accessible cable seating and power indicators.'],['Observa los conectores accesibles y los indicadores de alimentación.']),
        'SLOW_INTERNET':(['throughput','signal','packet_loss','wired_or_wifi'],['simulated_performance'],
            ['Describe whether the slowdown affects a wired connection or only Wi-Fi.'],['Describe si la lentitud afecta una conexión por cable o solo Wi-Fi.']),
        'INTERMITTENT_CONNECTION':(['timing','affected_devices','last_diagnostic'],[],
            ['Note when the connection drops and whether multiple devices are affected.'],['Anota cuándo se interrumpe la conexión y si afecta a varios dispositivos.']),
        'NO_POWER':(['power_indicator','accessible_power_connection'],[],
            ['Observe whether the power indicator is lit and whether accessible power connections appear seated.','Do not handle damaged electrical equipment.'],
            ['Observa si el indicador de alimentación está encendido y si las conexiones accesibles están asentadas.','No manipules equipos eléctricos dañados.']),
        'WIFI_ISSUE':(['wired_comparison','distance','affected_devices'],[],
            ['Compare the behavior of another device and note your distance from the router.'],['Compara el comportamiento de otro dispositivo y anota tu distancia al router.']),
        'ADMIN_SUSPENDED':(['administrative_status'],['administrative_status'],
            ['Contact the authorized account-support operator; technical checks cannot remove a suspension.'],['Contacta al operador autorizado de cuentas; las comprobaciones técnicas no eliminan una suspensión.']),
    }
    for code,(evidence,tools,en,es) in rows.items():
        Category.objects.get_or_create(code=code,defaults={'title':code.replace('_',' ').title(),
            'relevant_evidence':evidence,'available_tools':tools,'safe_checks':{'en':en,'es':es},
            'documentation_requirements':['Exact model only for model-specific wiring or indicator semantics.'],
            'escalation_criteria':['Existing authorized ticket workflow and actual service diagnostics.'],
            'knowledge_sources':['Approved documents','Verified and reviewed organization cases']})


class Migration(migrations.Migration):
    dependencies=[('knowledge','0003_troubleshootingcategory_caseresolution_caseaudit_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
