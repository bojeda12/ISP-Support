from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html
from .models import ReferenceDocument, KnowledgeSection
from .services import ingest, approve, validate_pdf
from .models import SupportOrganization, TroubleshootingCategory, CaseResolution, CaseAudit, CaseUsage
from .cases import verify_case, review_case


@admin.register(SupportOrganization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display=('name','code','retention_days')

    def has_module_permission(self,request):
        return request.user.is_superuser

    def has_view_permission(self,request,obj=None):
        return request.user.is_superuser

    has_add_permission=has_view_permission
    has_change_permission=has_view_permission
    has_delete_permission=has_view_permission


@admin.register(TroubleshootingCategory)
class CategoryAdmin(admin.ModelAdmin):
    list_display=('code','title','active')
    search_fields=('code','title')

    def has_change_permission(self,request,obj=None):
        return request.user.is_superuser

    has_add_permission=has_change_permission
    has_delete_permission=has_change_permission


class CaseAuditInline(admin.TabularInline):
    model=CaseAudit
    extra=0
    fields=('actor','action','revision','created_at')
    readonly_fields=fields
    can_delete=False

    def has_add_permission(self,request,obj=None):
        return False


class CaseUsageInline(admin.TabularInline):
    model=CaseUsage
    extra=0
    fields=('conversation','revision','reason','external_context_injected','created_at')
    readonly_fields=fields
    can_delete=False

    def has_add_permission(self,request,obj=None):
        return False


@admin.register(CaseResolution)
class CaseResolutionAdmin(admin.ModelAdmin):
    list_display=('id','organization','category','equipment_category','approval','restoration_confirmed','revision','expires_at')
    list_filter=('approval','category','restoration_confirmed')
    search_fields=('reported_symptoms','technical_findings','verified_root_cause')
    readonly_fields=('approval','revision','technician_verified_by','verified_at','approved_by','approved_at','approved_fingerprint','created_at','updated_at')
    inlines=(CaseAuditInline,CaseUsageInline)
    actions=('verify_selected','approve_selected','withdraw_selected','reject_selected')

    def get_queryset(self,request):
        qs=super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(organization__members=request.user)

    def has_view_permission(self,request,obj=None):
        return super().has_view_permission(request,obj) and (obj is None or request.user.is_superuser or obj.organization.members.filter(pk=request.user.pk).exists())

    def has_change_permission(self,request,obj=None):
        return super().has_change_permission(request,obj) and self.has_view_permission(request,obj)

    def has_delete_permission(self,request,obj=None):
        return super().has_delete_permission(request,obj) and self.has_view_permission(request,obj)

    def get_readonly_fields(self,request,obj=None):
        fields=list(self.readonly_fields)
        if obj:
            fields += ['organization']
        if not request.user.has_perm('knowledge.review_caseresolution'):
            fields += ['privacy_reviewed','reuse_authorized','policy_reference','allow_external_ai','expires_at']
        return fields

    def formfield_for_foreignkey(self,db_field,request,**kwargs):
        if db_field.name=='organization' and not request.user.is_superuser:
            kwargs['queryset']=SupportOrganization.objects.filter(members=request.user)
        if db_field.name=='source_ticket' and not request.user.is_superuser:
            from tickets.models import Ticket
            kwargs['queryset']=Ticket.objects.filter(customer__organization__members=request.user)
        return super().formfield_for_foreignkey(db_field,request,**kwargs)

    def save_model(self,request,obj,form,change):
        from .cases import authorized
        authorized(request.user,obj.organization,'knowledge.change_caseresolution' if change else 'knowledge.add_caseresolution')
        obj.full_clean()
        obj.save()
        from .cases import snapshot
        CaseAudit.objects.create(case=obj,actor=request.user,action='EDITED' if change else 'CREATED',revision=obj.revision,snapshot=snapshot(obj))

    def apply_review(self,request,queryset,decision=None):
        for case in queryset:
            try:
                if decision:
                    review_case(case=case,user=request.user,decision=decision)
                else:
                    verify_case(case=case,user=request.user)
            except (ValidationError,PermissionDenied) as error:
                self.message_user(request,str(error),level=messages.ERROR)

    @admin.action(description='Verificar hallazgos y restauración como técnico')
    def verify_selected(self,request,queryset):
        self.apply_review(request,queryset)

    @admin.action(description='Aprobar resumen para recuperación interna')
    def approve_selected(self,request,queryset):
        self.apply_review(request,queryset,'APPROVED')

    @admin.action(description='Retirar conocimiento desactualizado')
    def withdraw_selected(self,request,queryset):
        self.apply_review(request,queryset,'WITHDRAWN')

    @admin.action(description='Rechazar resumen')
    def reject_selected(self,request,queryset):
        self.apply_review(request,queryset,'REJECTED')


class ReferenceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['visibility'].required = False

    def clean_visibility(self):
        return self.cleaned_data.get('visibility') or ReferenceDocument.Visibility.INTERNAL

    class Meta:
        model = ReferenceDocument
        fields = '__all__'
        widgets = {'pdf': forms.FileInput()}

    def clean_pdf(self):
        value = self.cleaned_data.get('pdf')
        if value and hasattr(value, 'content_type'):
            validate_pdf(value)
        return value


@admin.register(ReferenceDocument)
class ReferenceAdmin(admin.ModelAdmin):
    form = ReferenceForm
    list_display = ('title','revision','customer','equipment_model','language','category','approval','index_status','active')
    list_filter = ('approval','category','language','index_status','active')
    search_fields = ('title','code','manufacturer','equipment_model','customer__external_id')
    readonly_fields = ('approval','uploaded_at','index_status','index_report','content_hash','private_download')
    actions = ['index_documents','approve_documents']

    def has_delete_permission(self,request,obj=None):
        return False

    @admin.display(description='Private PDF')
    def private_download(self,obj):
        if not obj or not obj.pdf:
            return '—'
        return format_html('<a href="{}">Download for operator review</a>',reverse('admin:knowledge_reference_download',args=[obj.pk]))

    def get_readonly_fields(self, request, obj=None):
        fields = self.readonly_fields
        if not request.user.has_perm('knowledge.approve_reference'):
            fields += ('customer_safe','allow_external_ai','visibility')
        return fields

    def save_model(self, request, obj, form, change):
        if change and form.changed_data:
            obj.approval = ReferenceDocument.Approval.DRAFT
            if set(form.changed_data) & {'pdf','structured_text'}:
                obj.index_status = ReferenceDocument.IndexStatus.PENDING
        super().save_model(request,obj,form,change)

    @admin.action(description='Extract/index selected documents (resets approval)', permissions=['change'])
    def index_documents(self, request, queryset):
        for doc in queryset:
            report = ingest(doc)
            self.message_user(request, f'{doc.code}: {doc.index_status}; {report}', messages.INFO)

    def has_approve_permission(self, request):
        return request.user.has_perm('knowledge.approve_reference')

    @admin.action(description='Approve reviewed documents; retire replaced revision', permissions=['approve'])
    def approve_documents(self, request, queryset):
        for doc in queryset:
            try:
                approve(doc)
                self.message_user(request,f'Approved: {doc.code}')
            except ValidationError as error:
                self.message_user(request, '; '.join(error.messages), messages.ERROR)

    def get_urls(self):
        return [path('<uuid:document_id>/download/',self.admin_site.admin_view(self.download), name='knowledge_reference_download')] + super().get_urls()

    def download(self, request, document_id):
        doc = self.get_object(request,str(document_id))
        if not doc or not self.has_view_permission(request,doc) or not doc.pdf:
            raise PermissionDenied
        response = FileResponse(doc.pdf.open('rb'), content_type='application/pdf', as_attachment=True, filename='reference.pdf')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


@admin.register(KnowledgeSection)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('document','page','ordinal','heading','language','approved_for_chat')
    list_filter = ('approved_for_chat','language','document')
    search_fields = ('heading','text','document__title')
    readonly_fields = ('document','page','ordinal','heading','language','text')

    def get_readonly_fields(self,request,obj=None):
        return self.readonly_fields + (() if request.user.has_perm('knowledge.approve_reference') else ('approved_for_chat',))

    def save_model(self,request,obj,form,change):
        obj.document.approval = ReferenceDocument.Approval.DRAFT
        obj.document.save(update_fields=['approval'])
        super().save_model(request,obj,form,change)

    def has_add_permission(self,request):
        return False

    def has_delete_permission(self,request,obj=None):
        return False
