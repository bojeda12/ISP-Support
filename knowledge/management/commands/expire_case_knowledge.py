"""Retira resúmenes caducados; borrado irreversible únicamente por opción explícita."""
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from knowledge.models import CaseResolution,CaseAudit


class Command(BaseCommand):
    help='Retira casos vencidos; --delete elimina casos y auditorías vencidos conforme a la política local.'

    def add_arguments(self,parser):
        parser.add_argument('--delete',action='store_true')
        parser.add_argument('--organization')

    @transaction.atomic
    def handle(self,*args,**options):
        qs=CaseResolution.objects.filter(expires_at__lte=timezone.now())
        if options['organization']:
            qs=qs.filter(organization__code=options['organization'])
        if options['delete']:
            if not options['organization']:
                raise CommandError('--delete requires an explicit --organization code.')
            count=qs.count(); qs.delete()
        else:
            qs=qs.filter(approval='APPROVED')
            count=0
            for case in qs:
                case.approval='WITHDRAWN'; case.save(update_fields=['approval'])
                CaseAudit.objects.create(case=case,actor=None,action='EXPIRED',revision=case.revision)
                count+=1
        self.stdout.write(f'Cases processed: {count}')
