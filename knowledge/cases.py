"""Casos minimizados y revisados; nunca se importan conversaciones ni fotografías."""
import hashlib
import json
import re
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from conversations.ai import normalize
from .models import CaseResolution, CaseAudit, CaseUsage

CONTENT_FIELDS=('category_id','language','equipment_category','manufacturer','equipment_model',
    'reported_symptoms','diagnostics','attempted_checks','visual_observations','ai_hypotheses',
    'technical_findings','verified_root_cause','resolution_steps','restoration_confirmed',
    'applicability','confidence','reuse_authorized','policy_reference','privacy_reviewed','allow_external_ai',
    'organization_id','source_ticket_id')


def snapshot(case):
    return {key:str(getattr(case,key)) if key.endswith('_id') else getattr(case,key) for key in CONTENT_FIELDS}


def fingerprint(case):
    return hashlib.sha256(json.dumps(snapshot(case),sort_keys=True).encode()).hexdigest()


def authorized(user, organization, permission):
    if not user or not user.is_active or not user.is_staff or not user.has_perm(permission) or (
        not user.is_superuser and not organization.members.filter(pk=user.pk).exists()):
        raise PermissionDenied('Authorized staff membership and case permission are required.')


def validate_case_content(case):
    text=' '.join(str(getattr(case,key)) for key in CONTENT_FIELDS if not key.endswith('_id'))
    if len(text)>12000:
        raise ValidationError('Summary exceeds the minimized case limit.')
    if re.search(r'https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b(?:\d{1,3}\.){3}\d{1,3}\b|(?:\+?\d[\s().-]?){9,}|\bISP-[A-Z0-9]+\b|ignore.{0,30}instructions|system prompt|api.?key|password|contrasena|ejecuta|execute|<[^>]+>',text,re.I):
        raise ValidationError('Remove identifiers, contact details, URLs, credentials and embedded instructions.')
    if not isinstance(case.diagnostics,dict) or set(case.diagnostics)-{'result_code','source','rssi_dbm','snr_db','latency_ms','packet_loss_percent','download_mbps','cpe_online'}:
        raise ValidationError('Use only non-identifying diagnostic fields.')
    if any(not isinstance(v,(str,int,float,bool,type(None))) for v in case.diagnostics.values()):
        raise ValidationError('Diagnostic values must be scalar.')
    if case.diagnostics.get('source') not in {None,'simulation','external'}:
        raise ValidationError('Diagnostic source must be simulation or external.')
    if 'result_code' in case.diagnostics and not re.fullmatch(r'[A-Z_]{1,64}',str(case.diagnostics['result_code'])):
        raise ValidationError('Use a diagnostic code, not identifying free text.')
    for key,value in case.diagnostics.items():
        if key not in {'source','result_code'} and value is not None and not isinstance(value,(int,float,bool)):
            raise ValidationError('Metrics must be numeric, boolean or unavailable.')
    if case.organization_id:
        from customers.models import Customer
        for customer in Customer.objects.filter(organization_id=case.organization_id).iterator():
            identifiers=[customer.name,customer.external_id,customer.email,customer.phone]
            identifiers += list(customer.services.values_list('service_identifier',flat=True))
            if any(len(value.strip())>=4 and normalize(value) in normalize(text) for value in identifiers if value):
                raise ValidationError('Remove customer and account identifiers from the reusable summary.')


@transaction.atomic
def verify_case(*,case,user):
    case=CaseResolution.objects.select_for_update().get(pk=case.pk)
    authorized(user,case.organization,'knowledge.change_caseresolution')
    case.full_clean()
    if case.source_ticket and case.source_ticket.status not in {'RESOLVED','CLOSED'}:
        raise ValidationError('Source ticket must be resolved before technician verification.')
    if not case.restoration_confirmed or not case.technical_findings or not case.verified_root_cause:
        raise ValidationError('A confirmed restoration and actual technical cause are required.')
    case.technician_verified_by=user; case.verified_at=timezone.now()
    case.approval=CaseResolution.Approval.DRAFT
    case.save()
    CaseAudit.objects.create(case=case,actor=user,action='VERIFIED',revision=case.revision,snapshot=snapshot(case))
    return case


@transaction.atomic
def review_case(*,case,user,decision):
    case=CaseResolution.objects.select_for_update().get(pk=case.pk)
    authorized(user,case.organization,'knowledge.review_caseresolution')
    if decision not in {'APPROVED','WITHDRAWN','REJECTED'}:
        raise ValidationError('Unsupported review decision.')
    if decision=='APPROVED':
        case.full_clean()
        if user.pk == case.technician_verified_by_id:
            raise ValidationError('An independent reviewer must approve the summary.')
        if not (case.technician_verified_by_id and case.verified_at and case.restoration_confirmed and
                case.privacy_reviewed and case.reuse_authorized and case.policy_reference.strip()):
            raise ValidationError('Verification, restoration, privacy review and an explicit reuse policy are required.')
        if case.source_ticket and case.source_ticket.status not in {'RESOLVED','CLOSED'}:
            raise ValidationError('The source incident is not resolved.')
        case.approved_by=user; case.approved_at=timezone.now()
        case.approved_fingerprint=fingerprint(case)
        case.expires_at=timezone.now()+timedelta(days=case.organization.retention_days)
    case.approval=decision
    case.save()
    CaseAudit.objects.create(case=case,actor=user,action=decision,revision=case.revision,snapshot=snapshot(case))
    return case


def retrieve_cases(*,customer,context,message,language):
    if not customer.organization_id:
        return []
    from .services import tokens
    category=context.get('issue_category','unknown')
    if category=='unknown':
        category=context.get('reported_issue')
    diagnostic=(context.get('diagnostic') or {}).get('result_code')
    equipment=' '.join([str(context.get('equipment_claim') or ''),message])
    query=tokens(message+' '+str(context.get('customer_reported_checks',[])))
    candidates=[]
    queryset=CaseResolution.objects.select_related('category').filter(
        organization_id=customer.organization_id,approval='APPROVED',category__active=True,
        restoration_confirmed=True,privacy_reviewed=True,reuse_authorized=True,
        expires_at__gt=timezone.now(),technician_verified_by__isnull=False,approved_by__isnull=False)
    from django.db.models import Q
    queryset=queryset.filter(Q(source_ticket__isnull=True)|Q(source_ticket__status__in=['RESOLVED','CLOSED'],source_ticket__customer__organization_id=customer.organization_id))
    for case in queryset.order_by('-approved_at')[:200]:
        if fingerprint(case)!=case.approved_fingerprint or case.category.code!=category:
            continue
        if case.manufacturer and normalize(case.manufacturer) not in normalize(equipment):
            continue
        if case.equipment_model and normalize(case.equipment_model) not in normalize(equipment):
            continue
        matches=len(query & tokens(' '.join([case.reported_symptoms,case.attempted_checks,case.visual_observations,
            case.technical_findings,case.verified_root_cause,case.resolution_steps])))
        code_match=bool(diagnostic and case.diagnostics.get('result_code')==diagnostic)
        if not matches and not code_match:
            continue
        score=matches+8*code_match+3*bool(case.equipment_model)+int(case.language in {language,'mul'})
        candidates.append((score,case,{'category_match':True,'diagnostic_match':code_match,'symptom_matches':matches,'equipment_scoped':bool(case.equipment_model or case.manufacturer)}))
    candidates.sort(key=lambda v:(-v[0],str(v[1].pk)))
    selected=candidates[:3]
    conflict=len({normalize(case.verified_root_cause) for _,case,_ in selected})>1
    return [{'case_id':str(case.pk),'revision':case.revision,'score':score,'reason':reason,
        'pattern':{'symptoms':case.reported_symptoms,'equipment_category':case.equipment_category,
            'diagnostic_result':case.diagnostics.get('result_code'),'verified_past_cause':case.verified_root_cause,
            'resolution_steps':case.resolution_steps,'applicability':case.applicability,
            'confidence':case.confidence,'restoration_confirmed':True,
            'uncertainty':'Supporting historical pattern, not proof of the current cause.',
            'conflicting_patterns':conflict},
        'external_allowed':bool(settings.KNOWLEDGE_ALLOW_EXTERNAL_AI and case.allow_external_ai)} for score,case,reason in selected]


def record_usage(*,conversation,cases,external_injected):
    for match in cases:
        # Revalida aprobación y alcance antes de guardar la auditoría.
        case=CaseResolution.objects.filter(pk=match['case_id'],organization_id=conversation.customer.organization_id,
            approval='APPROVED',revision=match['revision'],expires_at__gt=timezone.now()).first()
        if case and fingerprint(case)==case.approved_fingerprint:
            CaseUsage.objects.create(case=case,conversation=conversation,revision=case.revision,
                reason=match['reason'],external_context_injected=bool(external_injected and match['external_allowed']))
