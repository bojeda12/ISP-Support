import uuid
from django.core.exceptions import ValidationError
from django.db import models
from .storage import ReferenceStorage, reference_path
from django.conf import settings


class SupportOrganization(models.Model):
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL,blank=True,related_name='support_organizations')
    retention_days = models.PositiveIntegerField(default=365)

    def __str__(self):
        return self.name


class TroubleshootingCategory(models.Model):
    code = models.SlugField(max_length=40,unique=True)
    title = models.CharField(max_length=120)
    relevant_evidence = models.JSONField(default=list)
    available_tools = models.JSONField(default=list)
    safe_checks = models.JSONField(default=list)
    documentation_requirements = models.JSONField(default=list)
    escalation_criteria = models.JSONField(default=list)
    knowledge_sources = models.JSONField(default=list)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.code


class CaseResolution(models.Model):
    class Approval(models.TextChoices):
        DRAFT='DRAFT','Draft'
        APPROVED='APPROVED','Approved'
        WITHDRAWN='WITHDRAWN','Withdrawn'
        REJECTED='REJECTED','Rejected'

    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(SupportOrganization,on_delete=models.PROTECT,related_name='cases')
    source_ticket = models.ForeignKey('tickets.Ticket',null=True,blank=True,on_delete=models.SET_NULL,related_name='resolution_cases')
    category = models.ForeignKey(TroubleshootingCategory,on_delete=models.PROTECT)
    language = models.CharField(max_length=3,choices=[('en','English'),('es','Spanish'),('mul','Bilingual')],default='en')
    equipment_category = models.CharField(max_length=80)
    manufacturer = models.CharField(max_length=80,blank=True)
    equipment_model = models.CharField(max_length=80,blank=True)
    reported_symptoms = models.TextField()
    diagnostics = models.JSONField(default=dict,blank=True)
    attempted_checks = models.TextField(blank=True)
    visual_observations = models.TextField(blank=True)
    ai_hypotheses = models.TextField(blank=True)
    technical_findings = models.TextField()
    verified_root_cause = models.TextField(blank=True)
    resolution_steps = models.TextField()
    restoration_confirmed = models.BooleanField(default=False)
    technician_verified_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='verified_support_cases')
    verified_at = models.DateTimeField(null=True,blank=True)
    privacy_reviewed = models.BooleanField(default=False)
    reuse_authorized = models.BooleanField(default=False,help_text='Explicit consent or applicable ISP policy authorizes this minimized summary.')
    policy_reference = models.CharField(max_length=160,blank=True)
    allow_external_ai = models.BooleanField(default=False)
    confidence = models.CharField(max_length=12,choices=[('LOW','Low'),('MEDIUM','Medium'),('HIGH','High')],default='MEDIUM')
    applicability = models.TextField()
    approval = models.CharField(max_length=12,choices=Approval,default=Approval.DRAFT)
    revision = models.PositiveIntegerField(default=1)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='approved_support_cases')
    approved_at = models.DateTimeField(null=True,blank=True)
    approved_fingerprint = models.CharField(max_length=64,blank=True,editable=False)
    expires_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions=[('review_caseresolution','Can approve or withdraw verified support cases')]

    def clean(self):
        from .cases import validate_case_content
        validate_case_content(self)
        if self.source_ticket_id and self.source_ticket.customer.organization_id != self.organization_id:
            raise ValidationError('Source ticket must belong to the same ISP organization.')

    def __str__(self):
        return f'{self.category_id} · {self.pk} · r{self.revision}'

    def save(self,*args,**kwargs):
        from .cases import fingerprint
        if self.expires_at is None and self.organization_id:
            from datetime import timedelta
            from django.utils import timezone
            self.expires_at=timezone.now()+timedelta(days=self.organization.retention_days)
        invalidated=False
        if not self._state.adding:
            old=type(self).objects.get(pk=self.pk)
            if fingerprint(old)!=fingerprint(self):
                self.revision=old.revision+1
                self.approval=self.Approval.DRAFT
                self.verified_at=None
                self.technician_verified_by=None
                self.approved_fingerprint=''
                invalidated=True
                kwargs.pop('update_fields',None)
        super().save(*args,**kwargs)
        if invalidated:
            CaseAudit.objects.create(case=self,actor=None,action='REVISED',revision=self.revision,snapshot={})


class CaseAudit(models.Model):
    case = models.ForeignKey(CaseResolution,on_delete=models.CASCADE,related_name='audit')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    action = models.CharField(max_length=24)
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class CaseUsage(models.Model):
    case = models.ForeignKey(CaseResolution,on_delete=models.CASCADE,related_name='usages')
    conversation = models.ForeignKey('conversations.Conversation',on_delete=models.CASCADE)
    revision = models.PositiveIntegerField()
    reason = models.JSONField(default=dict)
    external_context_injected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ReferenceDocument(models.Model):
    class Visibility(models.TextChoices):
        INTERNAL = 'internal', 'Internal grounding only'
        DEMO = 'generic_demo', 'Generic demonstration grounding'
        MANUFACTURER = 'manufacturer', 'Customer-facing manufacturer reference'
        CUSTOMER = 'customer_approved', 'Explicitly approved for customer display'

    class Category(models.TextChoices):
        MANUFACTURER = 'manufacturer_manual', 'Manufacturer manual'
        SOP = 'isp_sop', 'ISP procedure'
        DEMO = 'generic_demo_reference', 'Generic demo reference'

    class Approval(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        APPROVED = 'APPROVED', 'Approved'
        RETIRED = 'RETIRED', 'Retired'

    class IndexStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        READY = 'READY', 'Ready'
        PARTIAL = 'PARTIAL', 'Partial; review required'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    customer = models.ForeignKey('customers.Customer', null=True, blank=True, on_delete=models.PROTECT,
                                 help_text='Required for private operational references; demo references may be shared.')
    manufacturer = models.CharField(max_length=100, blank=True)
    equipment_family = models.CharField(max_length=100, blank=True)
    equipment_model = models.CharField(max_length=100, blank=True)
    equipment_version = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=3, choices=[('en','English'),('es','Spanish'),('mul','Bilingual')], default='en')
    category = models.CharField(max_length=30, choices=Category, default=Category.DEMO)
    revision = models.CharField(max_length=60)
    approval = models.CharField(max_length=12, choices=Approval, default=Approval.DRAFT)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=300)
    effective_date = models.DateField(null=True, blank=True)
    review_date = models.DateField(null=True, blank=True)
    replaces = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    pdf = models.FileField(storage=ReferenceStorage, upload_to=reference_path, blank=True)
    structured_text = models.TextField(blank=True, help_text='Alternative to PDF; headings and paragraphs supported.')
    customer_safe = models.BooleanField(default=False, help_text='Explicit review permitting use in customer-facing replies.')
    visibility = models.CharField(max_length=24, choices=Visibility, default=Visibility.INTERNAL,
        help_text='Display policy only; does not authorize retrieval, external AI or PDF access.')
    allow_external_ai = models.BooleanField(default=False, help_text='Explicit authorization to send eligible excerpts to external AI; also requires environment setting.')
    index_status = models.CharField(max_length=12, choices=IndexStatus, default=IndexStatus.PENDING)
    index_report = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [('approve_reference', 'Can approve and authorize reference documents')]

    def clean(self):
        if self.category != self.Category.DEMO and not self.customer_id:
            raise ValidationError({'customer': 'Operational documents must be scoped to a customer in this single-ISP demo.'})
        if bool(self.pdf) == bool(self.structured_text.strip()):
            raise ValidationError('Supply exactly one PDF or structured text.')
        if self.structured_text and len(self.structured_text) > 200_000:
            raise ValidationError({'structured_text': 'Text exceeds the indexing limit.'})
        if self.replaces_id == self.pk:
            raise ValidationError({'replaces': 'Cannot replace the same document.'})
        if self.category != self.Category.DEMO and not (self.equipment_model or self.equipment_family):
            raise ValidationError('Operational references require an explicit equipment scope.')

    def __str__(self):
        return f'{self.title} · {self.revision}'


class KnowledgeSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(ReferenceDocument, on_delete=models.CASCADE, related_name='sections')
    page = models.PositiveIntegerField(null=True, blank=True)
    ordinal = models.PositiveIntegerField()
    heading = models.CharField(max_length=200)
    language = models.CharField(max_length=3, default='mul')
    text = models.TextField()
    approved_for_chat = models.BooleanField(default=False)

    class Meta:
        ordering = ['page', 'ordinal']
        constraints = [models.UniqueConstraint(fields=['document','ordinal'], name='unique_document_section')]

    def __str__(self):
        return f'{self.document.code} · p.{self.page or "—"} · {self.heading}'
