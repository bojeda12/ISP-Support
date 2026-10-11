"""Regresiones de decisiones conversacionales y herramienta de solo lectura."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.exceptions import PermissionDenied, ValidationError
from . import test_context, test_combined_turns
from .ai import Interpretation, DemoAIProvider, ProviderError
from .models import Message, Conversation
from .context import conversation_context
from .adaptive import authorized_recheck
from .visual_schema import VisualAnalysis
from diagnostics.services import set_demo_scenario
from tickets.models import Ticket

UNCERTAIN = "I already tried that, but I'm not sure if the connection is good."


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=False)
class AdaptiveTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select
    send = test_context.ContextTests.send
    start = test_context.ContextTests.start
    follow = test_context.ContextTests.follow
    post = test_combined_turns.CombinedTurnTests.post
    private_storage = test_combined_turns.CombinedTurnTests.private_storage

    def test_exact_demo_flow_two_photos_recheck_not_completed_or_escalated(self):
        self.private_storage(); self.select('en')
        initial=self.send("Hello, I don't have Internet. Can you help me?").json()
        self.conversation=Conversation.objects.get(pk=initial['conversation_id'])
        self.assertEqual(initial['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertEqual([x['step_number'] for x in initial['images']],[1,2,3,4])
        rear=self.post(UNCERTAIN,conversation_id=self.conversation.pk).json()
        self.assertIn('front',rear['message'])
        self.assertIsNone(rear['ticket']); self.assertIsNone(rear['diagnostic'])
        state=conversation_context(self.conversation)
        self.assertTrue(state['uncertain_checks']); self.assertFalse(state['confirmed_completed_checks'])
        self.assertIn('front_photo',state['pending_questions'])
        front=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(front['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertIsNone(front['ticket'])
        self.assertIn('new simulated check',front['message'])
        self.assertNotIn('Check the PoE injector',front['message'])
        self.assertEqual(self.conversation.photos.count(),2)
        self.assertEqual(self.conversation.messages.count(),6)
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertFalse(conversation_context(self.conversation)['confirmed_completed_checks'])
        done=self.follow('I already checked the power and cables.')
        self.assertEqual(done['ticket']['status'],'OPEN')
        self.assertIn('Customer uncertainty',Ticket.objects.get().description)
        self.assertIn('SIMULATED photo',Ticket.objects.get().description)
        self.assertEqual(self.follow('I already checked the power and cables.')['ticket']['number'],done['ticket']['number'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)

    def test_bad_openai_completed_classification_cannot_escalate_uncertain_attempt(self):
        self.private_storage(); self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory,patch('conversations.photos.get_provider') as vision:
            vision.return_value.analyze_photo.return_value=VisualAnalysis(observations=['Rear Ethernet plugs appear inserted; port lights are lit.'],uncertainties=['Port roles are unknown.'],recommended_actions=['CHECK_INDICATORS'],connectivity_confirmed=False)
            factory.return_value.interpret.return_value=Interpretation(intent='CONFIRM_PHYSICAL_CHECK',language='en',check_evidence='completed_report',next_action='recommend_escalation')
            factory.return_value.generate_reply.return_value={'answer':'The rear plugs and lights suggest a local link, but not Internet access. Could you show the front indicators?','question_kind':'front_photo'}
            result=self.post(UNCERTAIN,conversation_id=self.conversation.pk).json()
        self.assertEqual(result['intent'],'PHOTO_QUESTION')
        self.assertIn('rear plugs',result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)
        self.assertEqual(Ticket.objects.count(),0)

    def test_diagnostic_time_budget_rolls_back_result(self):
        self.start()
        from .models import DemoChatSession
        session=DemoChatSession.objects.get(pk=self.client.session['demo_session_id'])
        with patch('conversations.adaptive.monotonic',side_effect=[0,6]),self.assertRaises(ValidationError):
            authorized_recheck(session=session,conversation=self.conversation,message='checked',completed=True)
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)

    def test_service_frequency_limit_without_previous_run_is_handled(self):
        self.start()
        from .models import DemoChatSession
        session=DemoChatSession.objects.get(pk=self.client.session['demo_session_id'])
        fresh=Conversation.objects.create(customer=self.service.customer,internet_service=self.service)
        with override_settings(CHAT_DIAGNOSTIC_MAX_PER_HOUR=1),self.assertRaises(ValidationError):
            authorized_recheck(session=session,conversation=fresh,message='No Internet')
        self.assertFalse(conversation_context(self.conversation)['completed_checks'])

    def test_negative_control_reproduces_original_unchecked_intent_routing(self):
        self.private_storage(); self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.guard_interpretation',side_effect=lambda parsed,*args:parsed),patch('conversations.services.get_provider') as factory,patch('conversations.photos.get_provider') as vision:
            vision.return_value.analyze_photo.return_value=DemoAIProvider().analyze_photo(image=b'',mime_type='image/jpeg',language='en')
            factory.return_value.interpret.return_value=Interpretation(intent='CONFIRM_PHYSICAL_CHECK',language='en')
            self.post(UNCERTAIN,conversation_id=self.conversation.pk)
        # Sin la barrera de evidencia se reproduce la causa: intent -> recheck -> ticket.
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertEqual(Ticket.objects.count(),1)

    def test_openai_front_photo_receives_actual_tool_result_before_answer(self):
        self.private_storage(); self.start()
        self.post(UNCERTAIN,conversation_id=self.conversation.pk)
        with override_settings(AI_PROVIDER='openai',OPENAI_API_KEY='mock-only',OPENAI_MODEL='mock',OPENAI_VISION_MODEL='mock'),patch('conversations.ai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.parse.side_effect=[
                SimpleNamespace(status='completed',output_parsed=VisualAnalysis(observations=['Power and link indicators appear lit on the front.'],uncertainties=['Identity across photos is uncertain.'],recommended_actions=['CHECK_INDICATORS'],connectivity_confirmed=False)),
                SimpleNamespace(status='completed',output_parsed=Interpretation(intent='PHOTO_QUESTION',language='en',next_action='recheck')),
                SimpleNamespace(status='completed',output_parsed={'answer':'The front indicators are encouraging, but the new simulated check still cannot reach the outdoor equipment. Which accessible cable checks have you completed?','question_kind':'completed_checks'})]
            result=self.post('',conversation_id=self.conversation.pk).json()
            import json
            payload=json.loads(sdk.return_value.__enter__.return_value.responses.parse.call_args.kwargs['input'])
        self.assertTrue(payload['context']['tool_result']['executed'])
        self.assertFalse(payload['context']['tool_result']['metrics']['cpe_online'])
        self.assertEqual(len(payload['context']['photos']),2)
        self.assertIn('front indicators',result['message'])
        self.assertEqual(result['debug']['chat']['answer_provider'],'openai')
        self.assertEqual(Ticket.objects.count(),0)

    def test_recheck_healthy_never_opens_ticket(self):
        self.private_storage(); self.start(); self.post(UNCERTAIN,conversation_id=self.conversation.pk)
        set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['diagnostic']['result_code'],'NO_FAULT_DETECTED')
        self.assertEqual(Ticket.objects.count(),0)

    def test_uncertainty_spanish_and_no_repeat_front_request(self):
        self.private_storage(); self.start()
        result=self.post('Ya intenté, pero no estoy seguro de la conexión.',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['language'],'es'); self.assertIn('frontal',result['message'])
        repeated=self.follow('No estoy seguro de la conexión.')
        self.assertNotIn('parte frontal',repeated['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)

    def test_provider_failure_never_executes_proposed_actions(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.side_effect=ProviderError('timeout')
            result=self.follow(UNCERTAIN)
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)
        self.assertEqual(Ticket.objects.count(),0)

    def test_explicit_ticket_request_can_escalate_without_forcing_guide_steps(self):
        self.select('en')
        result=self.send('Please open a ticket for me.').json()
        self.assertEqual(result['ticket']['status'],'OPEN')

    def test_provider_failure_keeps_uncertainty_and_useful_question(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.side_effect=ProviderError('timeout')
            result=self.follow(UNCERTAIN)
        self.assertIn('Which connection',result['message'])
        self.assertTrue(conversation_context(self.conversation)['uncertain_checks'])
        self.assertFalse(conversation_context(self.conversation)['confirmed_completed_checks'])

    def test_reply_failure_after_authorized_escalation_reports_actual_ticket(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en',check_evidence='completed_report',next_action='recommend_escalation')
            factory.return_value.generate_reply.side_effect=ProviderError('timeout')
            result=self.follow('I already checked the power and cables.')
        self.assertEqual(result['ticket']['status'],'OPEN')
        self.assertIn(result['ticket']['number'],result['message'])
        self.assertEqual(result['requires_action'],'WAIT_FOR_TECHNICAL_REVIEW')

    def test_tool_refuses_other_customer_and_external_diagnostic(self):
        self.start()
        from .models import DemoChatSession
        session=DemoChatSession.objects.get(pk=self.client.session['demo_session_id'])
        other=Conversation.objects.create(customer=self.service.customer)
        with self.assertRaises(PermissionDenied):
            authorized_recheck(session=session,conversation=other,message='again',new_photo=True)
        self.conversation.diagnostic_runs.update(source='external')
        with self.assertRaises(PermissionDenied):
            authorized_recheck(session=session,conversation=self.conversation,message='again')

    def test_operational_reply_receives_result_and_saves_question(self):
        self.select('en')
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='NO_INTERNET',language='en',next_action='recheck')
            factory.return_value.generate_reply.return_value={'answer':'The simulated check cannot reach the CPE. Could you show the front indicators?','question_kind':'front_photo'}
            result=self.send("Hello, I don't have Internet. Can you help me?").json()
            supplied=factory.return_value.generate_reply.call_args.kwargs['context']
        self.assertEqual(supplied['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertTrue(supplied['tool_result']['executed'])
        self.assertEqual(result['debug']['chat']['answer_provider'],'openai')
        conversation=Conversation.objects.get(pk=result['conversation_id'])
        self.assertIn('front_photo',conversation_context(conversation)['pending_questions'])

    def test_tool_authorization_frequency_and_no_evidence_reuse(self):
        self.start()
        from .models import DemoChatSession
        session=DemoChatSession.objects.get(pk=self.client.session['demo_session_id'])
        prior=self.conversation.diagnostic_runs.first()
        run,trace=authorized_recheck(session=session,conversation=self.conversation,message='again')
        self.assertEqual(run.pk,prior.pk); self.assertEqual(trace['reason'],'no_new_evidence')
        with override_settings(CHAT_DIAGNOSTIC_MAX_PER_WINDOW=1):
            _,trace=authorized_recheck(session=session,conversation=self.conversation,message='checked',completed=True)
        self.assertEqual(trace['reason'],'frequency_limit')
        session.revoked=True; session.save()
        with self.assertRaises(PermissionDenied):
            authorized_recheck(session=session,conversation=self.conversation,message='checked',completed=True)

    def test_valid_openai_intent_is_not_replaced_by_short_phrase_router(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='EQUIPMENT_CLARIFICATION',language='en')
            factory.return_value.generate_reply.return_value={'answer':'That visible device looks like a gateway, but I cannot confirm its model.'}
            result=self.follow('is it good?')
        self.assertEqual(result['intent'],'EQUIPMENT_CLARIFICATION')
        self.assertIn('looks like a gateway',result['message'])
