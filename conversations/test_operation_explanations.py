"""Explicaciones basadas en operaciones confirmadas, sin llamadas facturables."""
import uuid
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from . import test_confirmed_recheck, test_combined_turns
from .models import Message
from tickets.models import Ticket

@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class OperationExplanationTests(TestCase):
    setUp=test_confirmed_recheck.ConfirmedRecheckTests.setUp
    select=test_confirmed_recheck.ConfirmedRecheckTests.select
    send=test_confirmed_recheck.ConfirmedRecheckTests.send
    start=test_confirmed_recheck.ConfirmedRecheckTests.start
    follow=test_confirmed_recheck.ConfirmedRecheckTests.follow
    post=test_confirmed_recheck.ConfirmedRecheckTests.post
    private_storage=test_confirmed_recheck.ConfirmedRecheckTests.private_storage
    sequence=test_confirmed_recheck.ConfirmedRecheckTests.sequence

    def test_photo_invalid_reply_preserves_acknowledgment_recheck_and_ticket(self):
        data=self.sequence(photo=True,misleading=True)
        self.assertIn('Thank you',data['message'])
        self.assertIn('photo',data['message'])
        self.assertIn('checked your connection again in the simulator',data['message'])
        self.assertIn('outdoor equipment is still not responding',data['message'])
        self.assertIn('opened a support ticket',data['message'])
        self.assertEqual(data['operation_outcome']['diagnostic']['execution'],'new')
        self.assertEqual(data['operation_outcome']['ticket']['action'],'created')
        self.assertEqual(data['debug']['chat']['fallback_reason'],'missing_ticket_result')
        self.assertEqual(data['debug']['chat']['answer_provider'],'django')
        self.assertTrue(data['operation_outcome']['diagnostic']['completed_at'])
        history=self.client.get(f'/api/conversations/{self.conversation.pk}/messages/').json()['messages']
        self.assertEqual(history[3]['operation_outcome'],data['operation_outcome'])

    def test_fresh_reused_measurement_is_not_described_as_new(self):
        data=self.sequence(rate_limited=True,misleading=True)
        self.assertEqual(data['operation_outcome']['diagnostic']['execution'],'reused')
        self.assertIn('latest available simulated network check',data['message'])
        self.assertIn('no new measurement',data['message'])
        self.assertNotIn('checked your connection again',data['message'])
        self.assertIn('limit',data['message'])

    def test_spanish_acknowledgment_and_result(self):
        data=self.sequence(photo=True,language='es',misleading=True)
        for text in ['Gracias','foto','Volví a comprobar','simulador','equipo exterior sigue sin responder','abrí un ticket','OPEN']:
            self.assertIn(text,data['message'])

    def test_healthy_recheck_has_no_false_failure_or_ticket(self):
        data=self.sequence(healthy=True,misleading=True)
        self.assertIn('no connectivity fault',data['message'])
        self.assertNotIn('still not responding',data['message'])
        self.assertIsNone(data['operation_outcome']['ticket'])

    def test_tool_failure_and_timeout_do_not_claim_new_measurement(self):
        self.start()
        for error in ['Tool unavailable','Simulated diagnostic exceeded its time budget.']:
            with patch('conversations.services.authorized_recheck',side_effect=ValidationError(error)):
                data=self.follow('I checked the cables, router and PoE power. Everything is connected but Internet still does not work.')
            self.assertIsNone(data['operation_outcome']['diagnostic'])
            self.assertIn('could not complete',data['message'])
            self.assertNotIn('I checked your connection again',data['message'])
            self.assertEqual(Ticket.objects.count(),0)
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)

    def test_photo_text_retry_reuses_response_and_existing_ticket(self):
        self.private_storage(); self.start(); key=uuid.uuid4()
        text="I checked the cables, router and PoE power. Everything is connected but Internet still doesn't work."
        first=self.post(text,conversation_id=self.conversation.pk,request_id=key)
        self.assertEqual(first.status_code,200,first.content)
        retry=self.post(text,conversation_id=self.conversation.pk,request_id=key)
        self.assertEqual(first.json(),retry.json())
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertEqual(self.conversation.photos.count(),1)
        self.assertEqual(Ticket.objects.count(),1)
        third=self.follow("I still don't have Internet.")
        self.assertEqual(third['operation_outcome']['ticket']['action'],'existing')
        self.assertEqual(third['ticket']['number'],first.json()['ticket']['number'])
        self.assertEqual(third['images'],[])
        self.assertNotIn('?',third['message'])

    def test_real_photo_observations_keep_uncertainty(self):
        from .operation_explanations import explain_operation
        context={'reported_checks_this_turn':True,'photos':[{'simulated':False,'status':'COMPLETED','observations':['A cable appears seated.']}],
                 'operation_outcome':{'diagnostic':{'execution':'reused','source':'simulation','result_code':'CPE_UNREACHABLE'},'ticket':None}}
        text=explain_operation(context,'en')
        self.assertIn('A cable appears seated.',text)
        self.assertIn('cannot confirm working hardware',text)

    def test_reused_result_cannot_be_presented_as_new_by_provider(self):
        from .adaptive import validate_tool_reply
        from .ai import ProviderError
        for text in ['I checked your connection again.','Volví a comprobar tu conexión.','A new measurement shows a fault.']:
            with self.assertRaises(ProviderError):
                validate_tool_reply(text,{'executed':False,'diagnostic_id':48,'reason':'no_new_evidence'},None)
        validate_tool_reply('The latest available check was reused; no new measurement was taken.',
                            {'executed':False,'diagnostic_id':48,'reason':'no_new_evidence'},None)

    def test_existing_ticket_cannot_be_claimed_as_new(self):
        from .operation_explanations import validate_operation_claims
        from .ai import ProviderError
        outcome={'ticket':{'number':'ISP-DEMO','status':'OPEN','action':'existing'}}
        for answer in ['I opened a support ticket ISP-DEMO.','He abierto un ticket ISP-DEMO.']:
            with self.assertRaises(ProviderError):
                validate_operation_claims(answer,outcome)
        validate_operation_claims('Your issue remains recorded under ticket ISP-DEMO: OPEN.',outcome)

    def test_valid_provider_keeps_ai_reply_and_receives_confirmed_outcome_once(self):
        from unittest.mock import Mock
        from .ai import Interpretation, DemoAIProvider
        from .decisions import Decision, Action
        from .operation_explanations import explain_operation
        self.private_storage(); self.start()
        provider=Mock(external_call_attempted=False)
        provider.interpret.return_value=Interpretation(intent='CONFIRM_PHYSICAL_CHECK',language='en',
            checks_attempted=True,check_evidence='completed_report',
            decision=Decision(action=Action.RUN_AUTHORIZED_RECHECK,reason='Customer reported checks.'))
        provider.generate_reply.side_effect=lambda **kwargs: {'answer':explain_operation(kwargs['context'],'en')}
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider',return_value=provider),patch('conversations.photos.get_provider',return_value=DemoAIProvider()),patch('conversations.ai.OpenAI',side_effect=AssertionError('Billable calls forbidden')):
            response=self.post("I checked the cables, router and PoE power. Everything is connected but Internet still doesn't work.",conversation_id=self.conversation.pk)
        self.assertEqual(response.status_code,200,response.content)
        data=response.json()
        self.assertEqual(data['debug']['chat']['response_source'],'openai_generated')
        self.assertFalse(data['debug']['chat']['fallback_used'])
        self.assertEqual(provider.interpret.call_count,1)
        self.assertEqual(provider.generate_reply.call_count,1)
        context=provider.generate_reply.call_args.kwargs['context']
        self.assertEqual(context['operation_outcome'],data['operation_outcome'])
        self.assertTrue(context['reported_checks_this_turn'])
