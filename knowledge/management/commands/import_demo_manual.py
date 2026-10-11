"""Importación local explícita del manual suministrado; nunca se descarga de una URL."""
from pathlib import Path
import hashlib
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from knowledge.models import ReferenceDocument
from knowledge.services import approve, ingest, validate_pdf


class Command(BaseCommand):
    help = 'Importa una copia privada del manual genérico; requiere revisión explícita de páginas para aprobar.'

    def add_arguments(self,parser):
        parser.add_argument('path')
        parser.add_argument('--code',default='isp-support-generic-demo-v1')
        parser.add_argument('--revision',default='1.0')
        parser.add_argument('--approve-pages',default='',help='Páginas revisadas, separadas por comas; omitir deja borrador.')

    def handle(self,*args,**options):
        path = Path(options['path'])
        if not path.is_file() or path.stat().st_size > 10*1024*1024:
            raise CommandError('PDF unavailable or too large.')
        raw = path.read_bytes()
        validate_pdf(SimpleUploadedFile('reference.pdf',raw,content_type='application/pdf'))
        digest = hashlib.sha256(raw).hexdigest()
        doc = ReferenceDocument.objects.filter(code=options['code']).first()
        if doc:
            if doc.content_hash != digest or doc.revision != options['revision']:
                raise CommandError('Existing code differs; create a new code/revision and review replacement explicitly.')
            self.stdout.write(f'Already indexed: {doc.code}; {doc.index_report}')
            return
        doc = ReferenceDocument(code=options['code'],title='ISP Support — Bilingual Troubleshooting Photo Manual',
            revision=options['revision'],language='mul',category='generic_demo_reference',
            source='User-supplied demo manual; generated images, generic equipment; not manufacturer instructions.',
            customer_safe=bool(options['approve_pages']),allow_external_ai=False)
        doc.pdf.save('reference.pdf',SimpleUploadedFile('reference.pdf',raw),save=False)
        try:
            doc.full_clean(); doc.save()
            report = ingest(doc)
            if options['approve_pages']:
                pages = [int(value) for value in options['approve_pages'].split(',')]
                if any(page not in report['pages_indexed'] for page in pages):
                    raise CommandError('Review list includes an unindexed page.')
                doc.sections.filter(page__in=pages).update(approved_for_chat=True)
                approve(doc)
            self.stdout.write(f'{doc.code}: {doc.approval}; {report}')
        except Exception:
            if not ReferenceDocument.objects.filter(pk=doc.pk).exists():
                doc.pdf.delete(save=False)
            raise
