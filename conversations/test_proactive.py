"""Visibilidad documental y elegibilidad explícita; sin llamadas reales a OpenAI."""
import uuid
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth.models import Permission
from knowledge.models import ReferenceDocument
from knowledge.services import validate_customer_answer
from diagnostics.services import set_demo_scenario
from tickets.models import Ticket
from . import test_context, test_combined_turns, test_knowledge_chat
from .models import Message, Conversation, ChatTurn
from .context import conversation_context
from .ai import Interpretation, ProviderError, DemoAIProvider


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class ProactiveTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select
    send = test_context.ContextTests.send
    start = test_context.ContextTests.start
    follow = test_context.ContextTests.follow
    post = test_combined_turns.CombinedTurnTests.post
    private_storage = test_combined_turns.CombinedTurnTests.private_storage
    reference = test_knowledge_chat.KnowledgeChatIntegrationTests.reference

    def rear(self, message="I already tried that, but I'm not sure if the connection is good."):
        self.private_storage()
        self.start()
        return self.post(message,conversation_id=self.conversation.pk).json()

    def test_internal_reference_hidden_but_local_provenance_retained(self):
        doc=self.reference(); doc.visibility='internal'; doc.save()
        result=self.post('Are these Ethernet cables connected?').json()
        self.assertNotIn(doc.title,result['message'])
        self.assertNotIn('Inspect accessible Ethernet connectors visually.',result['message'])
        self.assertEqual(result['citations'],[])
        self.assertEqual(result['debug']['knowledge']['retrieved_sources'],[])
        saved=Message.objects.get(sender='assistant').metadata
        self.assertEqual(saved['citations'][0]['document_id'],str(doc.pk))
        self.assertEqual(saved['knowledge']['citation_origin'],'django_local')
        self.assertFalse(saved['knowledge']['context_injected'])
        self.assertNotIn('consulted the manual',result['message'])

    def test_authorized_operator_can_audit_pages_in_development(self):
        doc=self.reference(); doc.visibility='internal'; doc.save()
        self.operator.user_permissions.add(Permission.objects.get(codename='view_referencedocument'))
        result=self.post('Are these Ethernet cables connected?').json()
        self.assertEqual(result['debug']['knowledge']['retrieved_sources'][0]['page'],1)
        self.assertNotIn(doc.title,result['message'])

    def test_customer_manufacturer_reference_is_concise_and_not_external_permission(self):
        doc=self.reference()
        doc.category=ReferenceDocument.Category.MANUFACTURER
        doc.customer=self.service.customer; doc.manufacturer='Fictional'; doc.equipment_model='ZX123'
        doc.visibility=ReferenceDocument.Visibility.MANUFACTURER; doc.save()
        result=self.post('Fictional ZX123 Ethernet cables connected?').json()
        self.assertIn(doc.title,result['message'])
        self.assertNotIn('p. 1',result['message']); self.assertNotIn('rev.',result['message'])
        self.assertNotIn('quote',result['citations'][0])
        self.assertFalse(result['debug']['knowledge']['context_injected'])
        self.assertFalse(doc.allow_external_ai)

    def test_old_history_hides_raw_internal_appendix_without_erasing_audit(self):
        doc=self.reference(); doc.visibility='internal'; doc.save()
        result=self.post('Are these Ethernet cables connected?').json()
        msg=Message.objects.get(sender='assistant')
        msg.content += f' [{doc.title}, p. 1, rev. 1]: “Inspect accessible Ethernet connectors visually.”'
        msg.save()
        history=self.client.get(f"/api/conversations/{result['conversation_id']}/messages/").json()
        self.assertNotIn(doc.title,history['messages'][-1]['content'])
        msg.refresh_from_db(); self.assertIn(doc.title,msg.content)

    def test_model_cannot_expose_internal_title_or_quote(self):
        doc=self.reference(); doc.visibility='internal'; doc.allow_external_ai=True; doc.save()
        with override_settings(AI_PROVIDER='openai',KNOWLEDGE_ALLOW_EXTERNAL_AI=True),patch('conversations.services.get_provider') as provider:
            provider.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en')
            provider.return_value.generate_reply.return_value={'answer':f'According to {doc.title}, the cable is connected.'}
            result=self.post('Are these Ethernet cables connected?',photo=False).json()
        self.assertNotIn(doc.title,result['message'])
        self.assertEqual(result['citations'],[])
        self.assertTrue(result['debug']['chat']['fallback_used'])
        with self.assertRaises(ProviderError):
            validate_customer_answer('“Inspect accessible Ethernet connectors visually.”',[{'title':doc.title,'excerpt':doc.structured_text or 'Inspect accessible Ethernet connectors visually.','customer_visible':False}])

    def test_attempt_rear_front_recheck_creates_one_ticket_without_completed_claim(self):
        rear=self.rear()
        self.assertIn('front',rear['message']); self.assertIsNone(rear['ticket'])
        key=uuid.uuid4()
        front=self.post('',conversation_id=self.conversation.pk,request_id=key).json()
        self.assertEqual(front['ticket']['status'],'OPEN')
        self.assertIn(front['ticket']['number'],front['message'])
        self.assertNotIn('completing those',front['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        state=conversation_context(self.conversation)
        self.assertFalse(state['confirmed_completed_checks'])
        self.assertFalse(state['trusted_verified_checks'])
        self.assertEqual(state['troubleshooting_stage'],'technical_review')
        self.assertEqual(state['pending_questions'],[])
        replay=self.post('',conversation_id=self.conversation.pk,request_id=key).json()
        self.assertEqual(replay,front)
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertIn('remain unverified',Ticket.objects.get().description)

    def test_two_photos_without_attempt_never_open_ticket(self):
        self.rear('')
        front=self.post('',conversation_id=self.conversation.pk).json()
        self.assertIsNone(front['ticket'])
        self.assertFalse(conversation_context(self.conversation)['confirmed_completed_checks'])
        self.assertEqual(Ticket.objects.count(),0)

    def test_uncertainty_without_attempt_does_not_qualify(self):
        self.rear("I'm not sure if it is good.")
        self.post('',conversation_id=self.conversation.pk)
        self.assertEqual(Ticket.objects.count(),0)
        self.follow("I haven't checked anything.")
        self.assertEqual(Ticket.objects.count(),0)

    def test_later_attempt_does_not_require_third_photo_or_exact_confirmation(self):
        self.rear('')
        self.post('',conversation_id=self.conversation.pk)
        result=self.follow("I tried checking the connections, but I'm not sure they are good.")
        self.assertEqual(result['ticket']['status'],'OPEN')
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertNotIn('show the front',result['message'])

    def test_inaccessible_checks_allow_review_without_photos(self):
        self.start()
        result=self.follow('I tried checking the cables, but I cannot access the remaining connections.')
        self.assertEqual(result['ticket']['status'],'OPEN')
        self.assertFalse(conversation_context(self.conversation)['confirmed_completed_checks'])
        self.assertEqual(self.conversation.photos.count(),0)

    def test_healthy_recheck_asks_about_browsing_without_ticket(self):
        self.rear()
        set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['diagnostic']['result_code'],'NO_FAULT_DETECTED')
        self.assertIn('browse',result['message'])
        self.assertEqual(Ticket.objects.count(),0)

    def test_spanish_attempt_and_front_photo_escalate_in_spanish(self):
        self.rear('Ya intenté revisar los cables, pero no estoy seguro de la conexión.')
        result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['language'],'es')
        self.assertIsNotNone(result['ticket'])
        self.assertIn('revisión técnica',result['message'])
        self.assertEqual(result['ticket']['status'],'OPEN')

    def test_frontier_identification_does_not_prompt_for_model_again(self):
        self.start()
        for _ in range(2):
            result=self.follow("It's a Frontier router.")
            self.assertNotIn('What exact model',result['message'])
            self.assertIn('without its exact model',result['message'])

    def test_openai_receives_ticket_before_natural_explanation(self):
        self.rear()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as provider,patch('conversations.photos.get_provider',return_value=DemoAIProvider()):
            provider.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en',next_action='ask_question',question_kind='equipment_model')
            def generate(**kwargs):
                self.assertEqual(len(kwargs['context']['photos']),2)
                self.assertTrue(kwargs['context']['tool_result']['executed'])
                ticket=kwargs['context']['active_ticket']
                self.assertEqual(ticket['status'],'OPEN')
                return {'answer':f"The check still cannot reach the outdoor equipment. Ticket {ticket['number']} is open for technical review."}
            provider.return_value.generate_reply.side_effect=generate
            result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['debug']['chat']['answer_provider'],'openai')
        self.assertIn(result['ticket']['number'],result['message'])
        self.assertNotIn('model',result['message'])

    def test_generation_failure_still_reports_authorized_ticket(self):
        self.rear()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as provider,patch('conversations.photos.get_provider',return_value=DemoAIProvider()):
            provider.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en',next_action='recheck')
            provider.return_value.generate_reply.side_effect=ProviderError('timeout')
            result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertIn(result['ticket']['number'],result['message'])
        self.assertTrue(result['debug']['chat']['fallback_used'])

    def test_policy_can_be_disabled_without_altering_ticket_rules(self):
        self.rear()
        with override_settings(CHAT_ALLOW_INCONCLUSIVE_REVIEW=False):
            result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertIsNone(result['ticket'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)

    def test_stale_measurement_does_not_authorize_new_review(self):
        from datetime import timedelta
        from django.utils import timezone
        self.rear()
        with override_settings(CHAT_ALLOW_INCONCLUSIVE_REVIEW=False):
            self.post('',conversation_id=self.conversation.pk)
        self.conversation.diagnostic_runs.update(completed_at=timezone.now()-timedelta(minutes=10))
        self.follow("I tried again, but I'm not sure it is good.")
        self.assertEqual(Ticket.objects.count(),0)

    def test_old_idempotent_response_cannot_replay_internal_citations(self):
        doc=self.reference(); doc.visibility='internal'; doc.save()
        key=uuid.uuid4()
        self.post('Are these Ethernet cables connected?',request_id=key)
        cached=ChatTurn.objects.get(request_id=key)
        cached.response['citations']=Message.objects.get(sender='assistant').metadata['citations']
        cached.response['message'] += f' [{doc.title}, p. 1, rev. 1]: “Inspect accessible Ethernet connectors visually.”'
        cached.save()
        result=self.post('Are these Ethernet cables connected?',request_id=key).json()
        self.assertNotIn(doc.title,result['message'])
        self.assertEqual(result['citations'],[])
        self.assertEqual(ChatTurn.objects.count(),1)
        cached.refresh_from_db(); self.assertIn(doc.title,cached.response['message'])

    def test_model_cannot_claim_nonexistent_ticket(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as provider:
            provider.return_value.interpret.return_value=Interpretation(intent='OTHER',language='en')
            provider.return_value.generate_reply.return_value={'answer':"I've created support ticket ISP-FAKE123 for you."}
            result=self.follow('What happens next?')
        self.assertNotIn('ISP-FAKE123',result['message'])
        self.assertIsNone(result['ticket'])
        self.assertEqual(result['debug']['chat']['fallback_reason'],'invalid_ticket_claim')
