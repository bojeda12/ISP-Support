"""Confirmación básica → herramienta → ticket; sin llamadas facturables."""
from unittest.mock import patch
from django.test import TestCase, override_settings
from diagnostics.services import set_demo_scenario
from tickets.models import Ticket
from . import test_completion
from .ai import DemoAIProvider, Interpretation, ProviderError
from .context import conversation_context
from .decisions import Action, Decision


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class ConfirmedRecheckTests(TestCase):
    setUp=test_completion.CompletionTests.setUp
    select=test_completion.CompletionTests.select
    send=test_completion.CompletionTests.send
    start=test_completion.CompletionTests.start
    follow=test_completion.CompletionTests.follow
    post=test_completion.CompletionTests.post
    private_storage=test_completion.CompletionTests.private_storage

    def test_original_ticket_claim_guard_still_rejects_claim_without_number(self):
        from .adaptive import validate_ticket_claim
        with self.assertRaisesMessage(ProviderError,'invalid_ticket_claim'):
            validate_ticket_claim('I have created a support ticket for you.',None)

    def sequence(self, *, photo=False, healthy=False, failure=None, rate_limited=False, language='en', misleading=False, inaccessible=False):
        self.private_storage(); self.start()
        before=list(self.conversation.diagnostic_runs.values('id','completed_at','result_code'))
        if healthy:
            set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        captured=[]
        demo=DemoAIProvider()
        class Provider:
            external_call_attempted=False
            def interpret(inner,**kwargs):
                inner.external_call_attempted=True
                if failure:
                    raise ProviderError(failure)
                # Reproduce la clasificación real 165: incertidumbre del modelo,
                # pese a la confirmación explícita del cliente.
                return Interpretation(intent='PHOTO_QUESTION',language=language,check_evidence='attempted_uncertain',
                    checks_attempted=True,supplied_evidence=['power','cable_path'],
                    additional_checks='unavailable' if inaccessible else 'available',
                    decision=Decision(action=Action.RUN_AUTHORIZED_RECHECK,reason='Customer reports completed basic checks.'))
            def generate_reply(inner,**kwargs):
                inner.external_call_attempted=True
                captured.append(kwargs['context'])
                if misleading:
                    return {'answer':'The next step is to run an authorized recheck.'}
                state=kwargs['context']
                answer=('El resultado simulado es ' if language=='es' else 'The simulated result is ')+state['diagnostic']['result_code']+'.'
                if state.get('ticket'):
                    answer+=' Ticket '+state['ticket']['number']+': '+state['ticket']['status']+'.'
                return {'answer':answer}
        text=('Sí, revisé la alimentación y los cables. El PoE tiene alimentación y todo está conectado.' if language=='es' else
              'Yes, I checked the power and cables. The PoE has power and everything is connected.')
        if inaccessible:
            text='I tried, but I cannot safely access the PoE or complete more checks.'
        limits={'CHAT_DIAGNOSTIC_MAX_PER_WINDOW':1} if rate_limited else {}
        from .adaptive import authorized_recheck
        from tickets.services import create_ticket
        with override_settings(AI_PROVIDER='openai',**limits),patch('conversations.services.get_provider',return_value=Provider()),patch('conversations.photos.get_provider',return_value=demo),patch('conversations.ai.OpenAI',side_effect=AssertionError('Billable calls forbidden')),patch('conversations.services.authorized_recheck',wraps=authorized_recheck) as recheck_call,patch('diagnostics.services.create_ticket',wraps=create_ticket) as ticket_call:
            result=(self.post(text,conversation_id=self.conversation.pk).json() if photo else self.follow(text))
        self.assertEqual(recheck_call.call_count,1)
        self.assertEqual(ticket_call.call_count,0 if healthy else 1)
        after=list(self.conversation.diagnostic_runs.values('id','completed_at','result_code'))
        self.assertEqual(len(after),1 if rate_limited else 2)
        self.assertEqual(Ticket.objects.count(),0 if healthy else 1)
        self.assertEqual(conversation_context(self.conversation)['trusted_verified_checks'],[])
        if not healthy:
            self.assertIn(result['ticket']['number'],result['message'])
            number=result['ticket']['number']
            follow=self.follow("I still don't have Internet.")
            self.assertIn(number,follow['message'])
            self.assertEqual(Ticket.objects.count(),1)
            self.assertEqual(self.conversation.diagnostic_runs.count(),len(after))
        if captured:
            self.assertEqual(captured[-1]['diagnostic']['id'],after[-1]['id'])
            self.assertEqual(captured[-1]['tool_result']['diagnostic_id'],after[-1]['id'])
            self.assertEqual(bool(captured[-1]['ticket']),not healthy)
        self.proof={'before':before,'after':after,'result':result,'ticket_count':Ticket.objects.count(),
            'authorized_recheck_calls':recheck_call.call_count,'create_ticket_calls':ticket_call.call_count}
        return result

    def test_confirmation_executes_recheck_and_ticket_without_photo(self):
        self.sequence()

    def test_confirmation_with_photo_executes_recheck_and_ticket(self):
        self.sequence(photo=True)

    def test_restored_service_does_not_create_ticket(self):
        self.sequence(healthy=True)

    def test_timeout_preserves_confirmation_and_executes(self):
        self.sequence(failure='timeout')

    def test_invalid_output_preserves_confirmation_and_executes(self):
        self.sequence(failure='invalid_output')

    def test_spanish_confirmation_executes(self):
        self.sequence(language='es')

    def test_rate_limit_reuses_actual_result_under_existing_confirmed_check_policy(self):
        result=self.sequence(rate_limited=True)
        self.assertEqual(result['debug']['chat']['tool_result']['reason'],'frequency_limit')
        self.assertFalse(result['debug']['chat']['tool_result']['executed'])
        self.assertTrue(result['debug']['chat']['tool_result']['fresh'])
        self.assertIn('limit',result['message'])

    def test_future_recheck_prose_cannot_replace_completed_operations(self):
        result=self.sequence(misleading=True)
        self.assertEqual(result['debug']['chat']['fallback_reason'],'missing_ticket_result')
        self.assertNotIn('next step',result['message'])

    def test_initial_healthy_service_has_one_measurement_no_ticket(self):
        self.select('en')
        set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        result=self.send("I don't have Internet.").json()
        self.assertEqual(result['diagnostic']['result_code'],'NO_FAULT_DETECTED')
        self.assertIsNone(result['ticket'])
        self.assertEqual(Ticket.objects.count(),0)

    def test_inaccessible_after_attempt_uses_existing_review_policy(self):
        self.sequence(inaccessible=True)

    def test_tool_failure_never_claims_second_measurement_or_ticket(self):
        from django.core.exceptions import ValidationError
        self.start()
        with patch('conversations.services.run_diagnostic',side_effect=ValidationError('Simulation unavailable')):
            result=self.follow('Yes, I checked the power and cables.')
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)
        self.assertIsNone(result['ticket'])
        self.assertEqual(result['requires_action'],'CONTACT_DEMO_OPERATOR')
        self.assertEqual(result['debug']['chat']['tool_result']['reason'],'operation_unavailable')

    def test_stale_rate_limited_result_is_not_used_to_create_ticket(self):
        from datetime import timedelta
        from django.utils import timezone
        self.start()
        self.conversation.diagnostic_runs.update(completed_at=timezone.now()-timedelta(minutes=6))
        with override_settings(CHAT_DIAGNOSTIC_MAX_PER_WINDOW=1):
            result=self.follow('Yes, I checked the power and cables.')
        self.assertIsNone(result['ticket'])
        self.assertIsNone(result['diagnostic'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)
        self.assertEqual(result['debug']['chat']['tool_result']['reason'],'stale_result_rate_limited')

    def test_reused_actual_measurement_cannot_be_described_as_future_recheck(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en',
                checks_attempted=True,check_evidence='attempted_uncertain',
                decision=Decision(action=Action.RUN_AUTHORIZED_RECHECK))
            factory.return_value.generate_reply.return_value={'answer':'The next step is to run an authorized recheck.'}
            first=self.follow("I tried, but I'm not sure about the cable.")
            reused=self.follow("So what's next?")
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertEqual(Ticket.objects.count(),0)
        self.assertEqual(reused['debug']['chat']['tool_result']['reason'],'no_new_evidence')
        self.assertEqual(first['debug']['chat']['tool_result']['diagnostic_id'],reused['debug']['chat']['tool_result']['diagnostic_id'])
        self.assertEqual(reused['debug']['chat']['fallback_reason'],'unexecuted_action_claim')
        self.assertNotIn('next step',reused['message'])
