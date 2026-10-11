"""Indexación local y recuperación léxica acotada, sin enviar documentos completos."""
import hashlib
import re
from io import BytesIO
from datetime import date
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from pypdf import PdfReader
from conversations.ai import normalize, ProviderError
from .models import ReferenceDocument as Document, KnowledgeSection as Section

PDF_MAX_BYTES = 10 * 1024 * 1024


def validate_pdf(upload):
    if upload.size > PDF_MAX_BYTES or not upload.name.lower().endswith('.pdf') or upload.content_type != 'application/pdf':
        raise ValidationError('Supply a PDF up to 10 MiB.')
    raw = upload.read(PDF_MAX_BYTES + 1)
    upload.seek(0)
    if len(raw) > PDF_MAX_BYTES or not raw.startswith(b'%PDF-'):
        raise ValidationError('Invalid PDF file.')
    try:
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError('unsupported_pdf')
    except Exception as error:
        raise ValidationError('Unreadable, encrypted or oversized PDF.') from error
    return raw


def sections(text):
    # Se conserva el orden y se divide en límites de líneas; sin resumir ni inventar texto.
    groups = re.split(r'(?=\b(?:STEP|PASO) [1-4]\b)|\n\s*\n', text)
    for group in groups:
        group = group.strip()
        while group:
            end = min(len(group), 1400)
            if end < len(group):
                boundary = group.rfind('\n',0,end)
                end = boundary if boundary > 0 else end
            chunk = group[:end].strip()
            if chunk:
                yield chunk
            group = group[end:].strip()


def ingest(document):
    report = {'pages_indexed': [], 'empty_pages': [], 'failed_pages': [], 'sections': 0, 'revision': document.revision}
    rows = []
    try:
        if document.pdf:
            with document.pdf.open('rb') as stream:
                raw = stream.read(PDF_MAX_BYTES + 1)
            if len(raw) > PDF_MAX_BYTES or not raw.startswith(b'%PDF-'):
                raise ValueError('invalid_pdf')
            reader = PdfReader(BytesIO(raw), strict=True)
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError('unsupported_pdf')
            pages = []
            for number, page in enumerate(reader.pages, 1):
                try:
                    contents = page.get_contents()
                    if contents and len(contents.get_data()) > 4_000_000:
                        raise ValueError('page_stream_limit')
                    text = page.extract_text() or ''
                    if len(text) > 100_000:
                        raise ValueError('page_text_limit')
                    pages.append((number, text))
                except Exception:
                    report['failed_pages'].append(number)
        else:
            raw = document.structured_text.encode('utf-8')
            if len(raw) > 800_000:
                raise ValueError('text_limit')
            pages = [(None, document.structured_text)]
        for page, text in pages:
            if not text.strip():
                report['empty_pages'].append(page)
                continue
            report['pages_indexed'].append(page)
            lang = document.language
            normalized = normalize(text[:300])
            if lang == 'mul':
                lang = 'es' if 'espanol' in normalized and 'english' not in normalized else 'en' if 'english' in normalized and 'espanol' not in normalized else 'mul'
            for chunk in sections(text):
                lines = chunk.splitlines()
                heading = ' · '.join(lines[:2]) if re.match(r'^(STEP|PASO) [1-4]$',lines[0]) else lines[0]
                rows.append(Section(document=document, page=page, ordinal=len(rows)+1,
                    heading=heading[:200], text=chunk, language=lang))
        status = Document.IndexStatus.FAILED if not rows else Document.IndexStatus.PARTIAL if report['empty_pages'] or report['failed_pages'] else Document.IndexStatus.READY
        document.content_hash = hashlib.sha256(raw).hexdigest()
    except Exception:
        status = Document.IndexStatus.FAILED
        report['error'] = 'extraction_failed'
    report['sections'] = len(rows)
    with transaction.atomic():
        document.sections.all().delete()
        Section.objects.bulk_create(rows)
        document.index_status = status
        document.index_report = report
        document.approval = Document.Approval.DRAFT
        document.save(update_fields=['index_status','index_report','content_hash','approval'])
    return report


def approve(document):
    document.full_clean()
    if document.index_status != Document.IndexStatus.READY or not document.sections.filter(approved_for_chat=True).exists():
        raise ValidationError('Index must be complete and customer sections explicitly reviewed before approval.')
    with transaction.atomic():
        if document.replaces_id:
            previous = Document.objects.select_for_update().get(pk=document.replaces_id)
            if previous.customer_id != document.customer_id or (previous.manufacturer,previous.equipment_model) != (document.manufacturer,document.equipment_model):
                raise ValidationError('Replacement scope must match the previous document.')
            previous.active = False
            previous.approval = Document.Approval.RETIRED
            previous.save(update_fields=['active','approval'])
        document.approval = Document.Approval.APPROVED
        document.save(update_fields=['approval'])


def tokens(text):
    aliases = {'wires':'ethernet','wire':'ethernet','cable':'ethernet','cables':'ethernet','conexiones':'ethernet','connectors':'ethernet',
               'connector':'ethernet','conector':'ethernet','conectores':'ethernet','connected':'ethernet','connections':'ethernet',
               'lights':'light','led':'light','leds':'light','luces':'light','luz':'light','indicador':'light','indicator':'light',
               'energia':'power','alimentacion':'power','inyector':'poe','injector':'poe','puerto':'port','puertos':'port'}
    stop = {'the','and','is','are','this','that','it','how','do','know','if','good','what','about','estos','esta','estan','como','que','para','con','los','las','una','del','por','bien','internet','support','isp'}
    return {aliases.get(t,t) for t in re.findall(r'[a-z0-9][a-z0-9-]+', normalize(text)) if t not in stop}


def contains(text, phrase):
    return bool(phrase and re.search(r'(?<![a-z0-9])'+re.escape(normalize(phrase))+r'(?![a-z0-9])', normalize(text)))


def retrieve(*, customer_id, message, context, language, query_text=None):
    equipment = ' '.join([message, (context.get('equipment_claim') or {}).get('text','')] +
                         [v.get('answer','') for v in context.get('answered_questions',[]) if v.get('question') == 'equipment_model'])
    query = tokens(query_text or message)
    if len(query) < 2:
        query |= tokens(' '.join(v for photo in context.get('photos',[])[:1] for v in photo.get('observations',[])))
    docs = Document.objects.filter(active=True, approval=Document.Approval.APPROVED,
        index_status=Document.IndexStatus.READY, customer_safe=True).filter(
            models_scope(customer_id)).filter(models_dates())
    exact, generic = [], []
    mismatches = 0
    for doc in docs[:200]:
        if doc.category == Document.Category.DEMO:
            generic.append(doc)
        elif (doc.manufacturer and not contains(equipment,doc.manufacturer)) or (doc.equipment_version and not contains(equipment,doc.equipment_version)):
            mismatches += 1
        elif doc.equipment_model and contains(equipment,doc.equipment_model):
            exact.append(doc)
        elif not doc.equipment_model and doc.equipment_family and contains(equipment,doc.equipment_family):
            exact.append(doc)
        else:
            mismatches += 1
    model_matches = [doc for doc in exact if doc.equipment_model]
    if model_matches:
        exact = model_matches
    preferred = [doc for doc in exact if doc.language in {language,'mul'}]
    if preferred:
        exact = preferred
    # Sin política de precedencia entre procedimientos aprobados en conflicto, no escoger uno.
    conflict = len(exact) > 1
    chosen = [] if conflict else exact or generic
    candidates = []
    for section in Section.objects.select_related('document').filter(document__in=chosen, approved_for_chat=True)[:500]:
        if re.search(r'ignore.{0,40}instructions|system prompt|api.?key|ignora.{0,40}instrucciones|execute|ejecuta', normalize(section.text)):
            continue
        matches = len(query & tokens(section.text))
        score = 4*matches + 3*len(query & tokens(section.heading)) + min(4,sum(bool(query & tokens(word)) for word in re.findall(r'[a-z0-9-]+',normalize(section.text)))) if matches else 0
        if score:
            candidates.append((score + (0.5 if section.language in {language,'mul'} else 0), section))
    candidates.sort(key=lambda item: (-item[0], str(item[1].document_id), item[1].ordinal))
    sources = []
    for _, section in candidates[:3]:
        doc = section.document
        sources.append({'section_id':str(section.pk), 'document_id':str(doc.pk), 'title':doc.title,
            'revision':doc.revision, 'page':section.page, 'heading':section.heading, 'excerpt':section.text,
            'generic':doc.category == Document.Category.DEMO,
            'customer_visible': doc.visibility == Document.Visibility.CUSTOMER or (doc.visibility == Document.Visibility.MANUFACTURER and doc.category == Document.Category.MANUFACTURER),
            'external_allowed':settings.KNOWLEDGE_ALLOW_EXTERNAL_AI and doc.allow_external_ai})
    return {'sources':sources, 'equipment_model':exact[0].equipment_model if exact and not conflict else None,
            'conflict':conflict, 'source_mismatch':bool(mismatches), 'specific_available':bool(exact) and bool(exact[0].equipment_model) and not conflict}


def models_scope(customer_id):
    from django.db.models import Q
    return Q(customer_id=customer_id) | Q(customer__isnull=True, category=Document.Category.DEMO)


def models_dates():
    from django.db.models import Q
    today = date.today()
    return (Q(effective_date__isnull=True)|Q(effective_date__lte=today)) & (Q(review_date__isnull=True)|Q(review_date__gte=today))


def validate_citations(citations, sources):
    allowed = {item['section_id']:item for item in sources}
    result = []
    for citation in citations:
        source = allowed.get(citation.section_id)
        if source is None or citation.quote not in source['excerpt']:
            raise ProviderError('invalid_citation')
        result.append({key:source[key] for key in ['section_id','document_id','title','revision','page','heading','generic']} | {'quote':citation.quote})
    return result


def citation_text(citations, language):
    return ' '.join(f'[{item["title"]}]' for item in citations)


def public_citations(citations, sources):
    visible = {item['section_id'] for item in sources if item.get('customer_visible')}
    return [{key:item[key] for key in ('document_id','section_id','title')} for item in citations if item['section_id'] in visible]


def validate_customer_answer(answer, sources):
    """No publicar identificadores ni citas textuales de referencias internas."""
    for source in sources:
        if source.get('customer_visible'):
            continue
        if source['title'].lower() in answer.lower() or re.search(r'\[[^\]]*,\s*p\.\s*\d+[^\]]*\]', answer):
            raise ProviderError('internal_reference_disclosure')
        for quote in re.findall(r'[“\"]([^”\"]{40,})[”\"]', answer):
            if quote in source['excerpt']:
                raise ProviderError('internal_reference_disclosure')
        for sentence in re.split(r'(?<=[.!?])\s+|\n',source['excerpt']):
            if len(sentence.strip()) >= 45 and sentence.strip() in answer:
                raise ProviderError('internal_reference_disclosure')
    return answer


def historical_customer_text(message):
    """Ocultar antiguos apéndices de citas sin reescribir la auditoría almacenada."""
    if message.sender != 'assistant':
        return message.content
    text = message.content
    for item in message.metadata.get('citations',[]):
        text = re.sub(r'\[' + re.escape(item['title']) + r',[^\]]*\]:\s*[“\"][^”\"]*[”\"]', '', text)
    text = text.replace('Generic demonstration reference; not verified model instructions.', '').replace('Referencia genérica de demostración; no son instrucciones verificadas del modelo.', '')
    return text.strip()


def replay_customer_payload(payload, session):
    from copy import deepcopy
    from types import SimpleNamespace
    from django.db.models import Q
    result = deepcopy(payload)
    citations = result.get('citations', [])
    result['message'] = historical_customer_text(SimpleNamespace(sender='assistant',content=result.get('message',''),metadata={'citations':citations}))
    allowed = set(Document.objects.filter(pk__in=[item['document_id'] for item in citations],active=True,
        approval=Document.Approval.APPROVED,customer_safe=True).filter(models_scope(session.internet_service.customer_id)).filter(models_dates()).filter(
        Q(visibility=Document.Visibility.CUSTOMER)|Q(visibility=Document.Visibility.MANUFACTURER,category=Document.Category.MANUFACTURER)).values_list('pk',flat=True))
    result['citations'] = [{key:item[key] for key in ('document_id','section_id','title')} for item in citations if str(item['document_id']) in {str(pk) for pk in allowed}]
    if 'debug' in result and not session.operator.has_perm('knowledge.view_referencedocument'):
        result['debug'].get('knowledge',{})['retrieved_sources'] = []
        result['debug'].get('knowledge',{})['retrieved_sections'] = []
    if 'debug' in result:
        customer=session.internet_service.customer
        if not session.operator.has_perm('knowledge.view_caseresolution') or not (session.operator.is_superuser or customer.organization_id and customer.organization.members.filter(pk=session.operator.pk).exists()):
            result['debug'].get('knowledge',{})['similar_cases']=[]
    return result
