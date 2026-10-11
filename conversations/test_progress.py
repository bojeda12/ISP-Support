"""Secuencia de once turnos, con proveedores locales o simulados exclusivamente."""
from unittest.mock import patch
from django.test import TestCase, override_settings
from diagnostics.services import set_demo_scenario
from tickets.models import Ticket
from .test_proactive import ProactiveTests
from .ai import DemoAIProvider, Interpretation, ProviderError
from .context import conversation_context


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class ProgressTests(TestCase):
    setUp = ProactiveTests.setUp
    select = ProactiveTests.select
    send = ProactiveTests.send
    start = ProactiveTests.start
    follow = ProactiveTests.follow
    post = ProactiveTests.post
    private_storage = ProactiveTests.private_storage

    def sequence(self, healthy=False, storage=True):
        if storage:
            self.private_storage()
        self.start()
        transcript = [self.post('Yes, I think everything looks fine, cables are connected.',conversation_id=self.conversation.pk).json()]
        if healthy:
            set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        for text in [
            'No, it does not have any labels.',
            'The yellow wire says Internet, and the black one is connected to Ethernet. Power is connected too.',
            "It's number 4, I think.", 'The black one is connected in port 4.',
            'Yeah, that has red and green lights.',
            'Yes, port four is visible. I already told you.',
            "I don't understand the question. I already gave you all the information I have.",
        ]:
            transcript.append(self.follow(text))
        transcript.append(self.post('',conversation_id=self.conversation.pk).json())
        transcript.append(self.follow("I still don't have Internet and I showed you the device. The cables are connected and the lights are on."))
        self.last_transcript=transcript
        return transcript

    def test_runtime_state_is_authenticated_and_identifies_policy(self):
        self.select('en')
        state=self.client.get('/demo/state/').json()
        self.assertEqual(state['runtime']['progress_policy_version'],2)
        self.assertTrue(state['runtime']['inconclusive_review'])
        self.client.logout()
        self.assertEqual(self.client.get('/demo/state/').status_code,302)

    def test_spanish_progress_persists_uncertain_reports(self):
        self.private_storage(); self.start()
        self.post('Ya revisé visualmente los cables conectados, pero no estoy seguro.',conversation_id=self.conversation.pk)
        result=self.post('',conversation_id=self.conversation.pk).json()
        self.assertEqual(result['language'],'es')
        self.assertIsNotNone(result['ticket'])
        self.assertFalse(conversation_context(self.conversation)['trusted_verified_checks'])

    def test_exact_sequence_demo_survives_refresh_and_deduplicates(self):
        results=self.sequence()
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.photos.count(),2)
        state=conversation_context(self.conversation)
        self.assertTrue(state['customer_reported_checks'])
        self.assertFalse(state['trusted_verified_checks'])
        self.assertTrue(state['answered_questions'])
        response=self.client.get(f'/api/conversations/{self.conversation.pk}/messages/')
        self.assertEqual(response.status_code,200)
        self.follow("I still don't have Internet and I showed you the device. The cables are connected and the lights are on.")
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertTrue(all(results[-2]['debug']['chat']['review_predicates'].values()))

    def test_healthy_exact_sequence_never_opens_ticket(self):
        self.sequence(healthy=True)
        self.assertEqual(Ticket.objects.count(),0)
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)

    def test_mock_openai_uncertainty_does_not_block_recheck(self):
        self.private_storage()
        demo=DemoAIProvider()
        class Provider:
            external_call_attempted=True
            def interpret(self, **kwargs):
                self.external_call_attempted=True
                raw=demo.interpret(**kwargs)
                if kwargs['history'][0]['context'].get('reported_issue'):
                    return Interpretation(intent='PHOTO_QUESTION',language='en',checks_attempted=True,
                        answers_pending=True,check_evidence='attempted_uncertain',next_action='ask_question',question_kind='indicator_label')
                return raw
            def generate_reply(self, **kwargs):
                self.external_call_attempted=True
                ticket=kwargs['context'].get('active_ticket')
                return {'answer':f"The simulated recheck still cannot reach your equipment. Technical review ticket {ticket['number']} is open." if ticket else 'I have recorded your observations; lights alone cannot confirm Internet connectivity.'}
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider',return_value=Provider()),patch('conversations.photos.get_provider',return_value=demo):
            results=self.sequence(storage=False)
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        self.assertEqual(results[-1]['debug']['chat']['answer_provider'],'openai')
        self.assertTrue(results[-1]['debug']['chat']['model_call_succeeded'])
        self.assertFalse(results[-1]['debug']['chat']['fallback_used'])

    def test_semantic_answer_records_uncertain_port_without_completed_claim(self):
        from .adaptive import progress_state
        state=progress_state({'pending_questions':['indicator_label']},
            Interpretation(intent='PHOTO_QUESTION',language='en',answers_pending=True),"It's number 4, I think.",5)
        self.assertEqual(state['pending_questions'],[])
        self.assertEqual(state['answered_questions'][0]['question'],'indicator_label')
        self.assertFalse(state['answered_questions'][0]['verified'])

    def test_redundant_question_repaired_by_model_preserves_natural_answer(self):
        self.start()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            provider=factory.return_value
            provider.external_call_attempted=True
            provider.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en')
            provider.generate_reply.side_effect=[
                {'answer':'What exact model is it?','question_kind':'equipment_model'},
                {'answer':'We can continue without a model number. Your reported connections do not yet establish Internet access.'}]
            result=self.follow('Is it good?')
        self.assertEqual(provider.generate_reply.call_count,2)
        self.assertEqual(result['debug']['chat']['answer_provider'],'openai')
        self.assertFalse(result['debug']['chat']['fallback_used'])
        self.assertIn('continue without a model',result['message'])
