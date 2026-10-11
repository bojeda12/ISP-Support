"""Réplicas sin facturación: acciones propuestas, ejecutadas y resultado de herramienta."""
from unittest.mock import patch
from django.test import TestCase, override_settings
from . import test_completion
from .ai import DemoAIProvider, ProviderError
from .decisions import Decision, Action, select_decision
from .context import conversation_context
from tickets.models import Ticket


class DecisionTests(TestCase):
    def test_openai_schema_requires_non_null_decision(self):
        from .ai import DecisionInterpretation
        from pydantic import ValidationError
        for data in [{'intent':'NO_INTERNET','language':'en'},
                     {'intent':'NO_INTERNET','language':'en','decision':None}]:
            with self.assertRaises(ValidationError):
                DecisionInterpretation.model_validate(data)

    def test_known_or_irrelevant_evidence_cannot_authorize_question(self):
        from .ai import Interpretation
        from types import SimpleNamespace
        for fact in ['ports','equipment_model','indicator_label']:
            parsed=Interpretation(intent='PHOTO_QUESTION',language='en',decision=Decision(
                action=Action.REQUEST_NECESSARY_EVIDENCE,required_fact=fact,reason='Identify exact port.'))
            _,accepted=select_decision(parsed,{'reported_issue':'NO_INTERNET','supplied_evidence':['ports']},
                SimpleNamespace(result_code='CPE_UNREACHABLE'),policy_enabled=True)
            self.assertEqual(accepted.action,Action.ANSWER_CUSTOMER)

    def test_unknown_power_can_materially_change_guidance(self):
        from .ai import Interpretation
        from types import SimpleNamespace
        parsed=Interpretation(intent='PHOTO_QUESTION',language='en',decision=Decision(
            action=Action.REQUEST_NECESSARY_EVIDENCE,required_fact='power',reason='Determine whether accessible power inspection is still useful.'))
        _,accepted=select_decision(parsed,{'reported_issue':'NO_INTERNET'},
            SimpleNamespace(result_code='CPE_UNREACHABLE'),policy_enabled=True)
        self.assertEqual(accepted.action,Action.REQUEST_NECESSARY_EVIDENCE)

    def test_inaccessible_checks_authorize_only_recheck_not_fabricated_ticket(self):
        from .ai import Interpretation
        from types import SimpleNamespace
        parsed=Interpretation(intent='PHOTO_QUESTION',language='es',decision=Decision(action=Action.ANSWER_CUSTOMER))
        _,accepted=select_decision(parsed,{'reported_issue':'NO_INTERNET','additional_checks':'unavailable'},
            SimpleNamespace(result_code='CPE_UNREACHABLE'),policy_enabled=True)
        self.assertEqual(accepted.action,Action.RUN_AUTHORIZED_RECHECK)

    def test_new_slow_incident_does_not_inherit_outage_recheck_priority(self):
        from .ai import Interpretation
        from types import SimpleNamespace
        parsed=Interpretation(intent='SLOW_INTERNET',issue_category='SLOW_INTERNET',language='en',decision=Decision(action=Action.ANSWER_CUSTOMER))
        _,accepted=select_decision(parsed,{'reported_issue':'NO_INTERNET','customer_reported_checks':[{'attempted':True}]},
            SimpleNamespace(result_code='CPE_UNREACHABLE'),policy_enabled=True)
        self.assertEqual(accepted.action,Action.ANSWER_CUSTOMER)


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class DecisionFlowTests(TestCase):
    setUp=test_completion.CompletionTests.setUp
    select=test_completion.CompletionTests.select
    send=test_completion.CompletionTests.send
    start=test_completion.CompletionTests.start
    follow=test_completion.CompletionTests.follow
    post=test_completion.CompletionTests.post
    private_storage=test_completion.CompletionTests.private_storage

    def test_material_power_question_records_reason_and_pending_fact(self):
        from .ai import Interpretation
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en',
                decision=Decision(action=Action.REQUEST_NECESSARY_EVIDENCE,required_fact='power',
                    reason='Accessible PoE power has not been reported; this determines whether power inspection is useful.'))
            factory.return_value.generate_reply.return_value={'answer':'Is the accessible PoE power indicator on?', 'question_kind':'power'}
            result=self.follow('What should I check next?')
        state=conversation_context(self.conversation)
        self.assertEqual(state['pending_questions'],['power'])
        self.assertTrue(state['asked_questions'][-1]['reason'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),1)
        self.assertIn('PoE',result['message'])

    def run_sequence(self, fail=False, healthy=False, classification_failure=False, invalid_citation=False, stale=False, redundant=False):
        from diagnostics.services import set_demo_scenario
        self.private_storage(); self.start()
        self.assertEqual(self.conversation.diagnostic_runs.get().result_code,'CPE_UNREACHABLE')
        demo=DemoAIProvider()
        observed=[]
        class Provider:
            external_call_attempted=False
            def interpret(inner,**kwargs):
                inner.external_call_attempted=True
                if stale and kwargs['message'].startswith('I already gave'):
                    from django.utils import timezone
                    from datetime import timedelta
                    self.conversation.diagnostic_runs.update(created_at=timezone.now()-timedelta(minutes=6),
                        completed_at=timezone.now()-timedelta(minutes=6))
                if classification_failure and kwargs['message'].startswith('I already gave'):
                    raise ProviderError('timeout')
                parsed=demo.interpret(**kwargs)
                return parsed.model_copy(update={'decision':Decision(action=Action.REQUEST_NECESSARY_EVIDENCE,
                    required_fact='indicator_label',reason='Identify the port.')})
            def generate_reply(inner,**kwargs):
                inner.external_call_attempted=True
                observed.append(kwargs['context'])
                if fail:
                    raise ProviderError('timeout')
                if redundant:
                    return {'answer':'What is the exact port label?','question_kind':'indicator_label'}
                saved=kwargs['context']
                answer='Your local cable and light reports cannot confirm Internet access. '
                if saved.get('photos'):
                    answer+='The photo analysis is simulated, not a verification of its contents. '
                if saved.get('diagnostic'):
                    answer+='The actual simulated result is '+saved['diagnostic']['result_code']+'. '
                if saved.get('ticket'):
                    answer+='Ticket '+saved['ticket']['number']+': '+saved['ticket']['status']+'.'
                result={'answer':answer.strip()}
                if invalid_citation:
                    result['citations']=[{'section_id':'not-a-retrieved-section','quote':'Fabricated support.'}]
                return result
        if healthy:
            set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider',return_value=Provider()),patch('conversations.photos.get_provider',return_value=demo),patch('conversations.ai.OpenAI',side_effect=AssertionError('Billable calls forbidden')):
            responses=[self.post('Is this connection good?',conversation_id=self.conversation.pk).json()]
            for text in ['The yellow cable is connected to the Internet port.','The other cable is for my computer.',
                         'The lights are on.','No, Internet still does not work.','I already gave you all the information I have.']:
                responses.append(self.follow(text))
        self.assertEqual(self.conversation.diagnostic_runs.count(),3 if stale else 2)
        self.assertTrue(all('?' not in r['message'] for r in responses if not healthy))
        self.assertIn('photo',responses[0]['message'].lower())
        self.assertTrue(any(c['tool_result']['executed'] and c['diagnostic']['id']==c['tool_result']['diagnostic_id'] for c in observed))
        state=conversation_context(self.conversation)
        self.assertTrue({'ports','equipment_role','indicators'}.issubset(state['supplied_evidence']))
        self.assertFalse(state['trusted_verified_checks'])
        self.assertEqual(Ticket.objects.count(),0 if healthy else 1)
        if not healthy:
            self.assertIsNotNone(responses[-1]['ticket'])
            self.assertIn(responses[-1]['ticket']['number'],responses[-1]['message'])
            self.assertEqual(state['pending_questions'],[])
            self.assertEqual(state['workflow_state'],'HANDOFF_PENDING')
            with patch('conversations.ai.OpenAI',side_effect=AssertionError('Billable calls forbidden')):
                after=self.follow('I still have no Internet.')
            self.assertIn(responses[-1]['ticket']['number'],after['message'])
            self.assertEqual(Ticket.objects.count(),1)
            self.assertEqual(self.conversation.diagnostic_runs.count(),3 if stale else 2)
        self.proof=[{'response':r['message'],'decision':r['debug']['chat']['decision'],
            'fallback':r['debug']['chat']['fallback_used'],'fallback_reason':r['debug']['chat']['fallback_reason']}
            for r in responses]
        if redundant:
            self.assertEqual(len(observed),2*len(responses))
        return responses

    def test_actual_sequence_executes_recheck_and_one_ticket(self):
        self.run_sequence()

    def test_reply_failure_preserves_operational_progress(self):
        results=self.run_sequence(fail=True)
        self.assertTrue(results[-1]['debug']['chat']['fallback_used'])
        self.assertIn(results[-1]['ticket']['number'],results[-1]['message'])

    def test_healthy_recheck_does_not_escalate(self):
        self.run_sequence(healthy=True)

    def test_classification_failure_keeps_saved_evidence_and_escalates(self):
        results=self.run_sequence(classification_failure=True)
        self.assertEqual(results[-1]['provider_status'],'unavailable')
        self.assertEqual(results[-1]['debug']['chat']['fallback_reason'],'timeout')

    def test_invalid_citation_cannot_undo_recheck_or_ticket(self):
        results=self.run_sequence(invalid_citation=True)
        self.assertEqual(results[-1]['debug']['chat']['fallback_reason'],'invalid_citation')
        self.assertFalse(results[-1]['debug']['chat']['reply_validated'])
        self.assertEqual(results[-1]['citations'],[])

    def test_stale_reused_result_is_refreshed_before_escalation(self):
        results=self.run_sequence(stale=True)
        self.assertTrue(results[-1]['debug']['chat']['tool_result']['executed'])
        self.assertTrue(results[-1]['debug']['chat']['review_predicates']['fresh_result'])

    def test_redundant_question_has_one_repair_then_useful_fallback(self):
        results=self.run_sequence(redundant=True)
        self.assertEqual(results[-1]['debug']['chat']['fallback_reason'],'redundant_evidence_request')
