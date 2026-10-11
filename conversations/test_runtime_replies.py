"""Pruebas de la ruta real del adaptador; SDK simulado, sin consumo externo."""
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch, Mock

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from openai import APITimeoutError

from . import test_context
from .ai import ConversationalReply, DemoAIProvider, Interpretation, OpenAIProvider, ProviderError
from .models import Message, ConversationPhoto
from .visual_schema import VisualAnalysis
from tickets.models import Ticket


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo')
class RuntimeReplyTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select
    send = test_context.ContextTests.send
    start = test_context.ContextTests.start
    follow = test_context.ContextTests.follow
    upload = test_context.ContextTests.upload

    def photo(self, observation):
        with patch('conversations.photos.get_provider') as factory:
            factory.return_value.analyze_photo.return_value = VisualAnalysis(
                observations=[observation], uncertainties=['Cable integrity cannot be verified visually.'],
                recommended_actions=['CHECK_INDICATORS'], connectivity_confirmed=False)
            self.assertEqual(self.upload().status_code, 201)
        ConversationPhoto.objects.filter(conversation=self.conversation).update(provider='openai')

    def generated(self, message, answer, focus='general', intent='PHOTO_QUESTION'):
        with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect = [
                SimpleNamespace(status='completed', output_parsed=Interpretation(intent=intent, language='en', photo_focus=focus)),
                SimpleNamespace(status='completed', output_parsed={'answer': answer,
                    'question_kind': 'indicator_label' if '?' in answer else 'none'})]
            with self.assertLogs('conversations.runtime', level='INFO') as logs:
                result = self.follow(message)
            self.assertEqual(client.responses.parse.call_count, 2)
            call = client.responses.parse.call_args.kwargs
            self.assertFalse(call['store'])
            self.assertNotIn('tools', call)
            self.assertEqual(call['max_output_tokens'], 900)
            self.assertIs(call['text_format'], ConversationalReply)
            self.assertIn('sole network authority', call['instructions'])
            self.assertIn('one useful follow-up', call['instructions'])
            self.assertIn('practical safe next steps', call['instructions'])
            payload = json.loads(call['input'])
            self.assertEqual(payload['message'], message)
            self.assertEqual(payload['context']['reported_issue'], 'NO_INTERNET')
            self.assertLessEqual(len(payload['context']['photos']), 3)
            self.assertNotIn('storage_key', call['input'])
            self.assertNotIn('mock-only', str(logs.output))
            self.assertNotIn(message, str(logs.output))
            provenance = self.conversation.messages.filter(sender='assistant').last().metadata['provenance']
            self.assertEqual(provenance['response_source'], 'openai_generated')
            self.assertTrue(provenance['classification_call_attempted'])
            self.assertTrue(provenance['reply_call_attempted'])
            self.assertFalse(provenance['fallback_used'])
            self.assertTrue(result['message'].startswith(answer))
            self.assertNotIn('approved instructions are unavailable',result['message'])
            if '?' in answer:
                self.assertIn('indicator_label', self.conversation.messages.filter(sender='assistant').last().metadata['context']['unresolved_questions'])
            return result, payload

    def test_front_photo_positive_evidence_uncertainty_and_network_authority(self):
        self.start(); self.photo('A green power indicator is visible on the front.')
        answer = ('The visible green power indicator is a positive sign that the device has power. '
            'It does not prove Internet access: the simulated network check still cannot reach the outdoor CPE. '
            'Which labeled link indicator is lit?')
        result, payload = self.generated('Is it good?', answer)
        self.assertIn('green power', payload['context']['photo']['observations'][0])
        self.assertIn('does not prove Internet', result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(result['images'], [])

    def test_connection_question_gets_practical_visual_checks_after_prior_question(self):
        self.start(); self.photo('A power light is visible.')
        self.follow('Is it good?')
        answer = ('Look at the accessible Ethernet connectors: each should appear fully seated, '
            'with no obvious damage to the plug or cable. Observe the labeled Ethernet link '
            'indicator; a light suggests a local link, not confirmed Internet access. '
            'Which device and labeled port are you checking?')
        result, payload = self.generated('How do I know if it is properly connected?', answer, 'connections')
        self.assertEqual(payload['focus'], 'connections')
        self.assertIn('fully seated', result['message'])
        self.assertNotIn('observations have not changed', result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)

    def test_rear_photo_question_uses_latest_and_retains_front(self):
        self.start(); self.photo('Front power indicator is lit.'); self.photo('Rear Ethernet plugs appear inserted.')
        answer = ('The saved rear-photo observation shows Ethernet plugs appearing inserted. '
            'That cannot establish cable integrity or Internet access. Visually check the accessible '
            'plugs for seating and damage and observe their labeled link indicators.')
        result, payload = self.generated('The wires are good?', answer, 'connections')
        self.assertIn('Rear Ethernet', payload['context']['photos'][0]['observations'][0])
        self.assertIn('Front power', payload['context']['photos'][1]['observations'][0])
        self.assertIn('cannot establish cable integrity', result['message'])

    def test_completed_checks_remain_deterministic_and_reuse_ticket(self):
        self.start()
        with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status='completed',
                output_parsed=Interpretation(intent='CONFIRM_PHYSICAL_CHECK', language='en'))
            first = self.follow('I already checked everything and still have no Internet.')
            second = self.follow('I already checked everything and still have no Internet.')
            self.assertEqual(client.responses.parse.call_count, 2)  # Solo clasificación por turno.
        self.assertEqual(first['ticket']['number'], second['ticket']['number'])
        self.assertEqual(first['ticket']['status'], 'OPEN')
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(first['images'], [])
        self.assertIn('Thank you for completing', first['message'])

    def test_generation_timeout_is_honest_local_fallback_and_no_demo_switch(self):
        self.start(); self.photo('Rear Ethernet plugs are visible.')
        with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.parse.side_effect = [
                SimpleNamespace(status='completed', output_parsed=Interpretation(intent='PHOTO_QUESTION', language='en', photo_focus='connections')),
                APITimeoutError(request=Mock())]
            result = self.follow('The wires are good?')
        self.assertEqual(result['provider_status'], 'reply_unavailable')
        self.assertIn('I can give limited guidance', result['message'])
        self.assertIn('seated connector', result['message'])
        provenance = self.conversation.messages.filter(sender='assistant').last().metadata['provenance']
        self.assertEqual(provenance['effective_provider'], 'openai')
        self.assertEqual(provenance['response_source'], 'reply_error_fallback')
        self.assertTrue(provenance['fallback_used'])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_demo_exact_questions_and_escalation_classification(self):
        for text in ('Is it good?', 'How do I know if it is properly connected?', 'The wires are good?'):
            result = DemoAIProvider().interpret(message=text, history=[], language='en')
            self.assertEqual(result.intent, 'PHOTO_QUESTION')
        self.assertEqual(DemoAIProvider().interpret(message='I already checked everything and still have no Internet.',
            history=[], language='en').intent, 'CONFIRM_PHYSICAL_CHECK')

    def test_spanish_generated_answer_preserves_language_and_memory(self):
        self.start(); self.photo('Se observa un conector Ethernet insertado.')
        answer = ('El conector parece insertado según la observación guardada, pero no confirma acceso a Internet. '
            'Comprueba visualmente que esté asentado y sin daños evidentes. ¿Qué indicador de enlace está encendido?')
        with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect = [
                SimpleNamespace(status='completed', output_parsed=Interpretation(intent='PHOTO_QUESTION', language='es', photo_focus='connections')),
                SimpleNamespace(status='completed', output_parsed={'answer': answer})]
            result = self.follow('¿Los cables están bien?')
            self.assertEqual(result['language'], 'es')
            self.assertTrue(result['message'].startswith(answer))
            self.assertNotIn('no dispone de instrucciones aprobadas',result['message'])
            self.assertEqual(json.loads(client.responses.parse.call_args.kwargs['input'])['language'], 'es')
        self.assertEqual(result['images'], [])

    def test_classifier_failure_skips_generation_and_marks_error_source(self):
        self.start()
        with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect = APITimeoutError(request=Mock())
            result = self.follow('Is it good?')
            self.assertEqual(client.responses.parse.call_count, 1)
        provenance = self.conversation.messages.filter(sender='assistant').last().metadata['provenance']
        self.assertEqual(result['provider_status'], 'unavailable')
        self.assertEqual(provenance['response_source'], 'provider_error')
        self.assertTrue(provenance['fallback_used'])
        self.assertFalse(provenance['reply_call_attempted'])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_local_connection_fallback_is_useful_without_photo(self):
        self.start()
        result = self.follow('How do I know if it is properly connected?')
        self.assertIn('seated connector', result['message'])
        self.assertIn('labeled link indicator', result['message'])
        self.assertIn('does not prove cable integrity or Internet access', result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)

    def test_generation_failure_malformed_or_unsafe_reply_does_not_execute_actions(self):
        self.start()
        for output in ({'answer': 'Reset the router.'}, {'answer': 'One? Two?'}, {'answer': 'OK', 'ticket_status': 'CLOSED'}):
            with override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='mock-only', OPENAI_MODEL='gpt-4.1-mini'), patch('conversations.ai.OpenAI') as sdk:
                sdk.return_value.__enter__.return_value.responses.parse.side_effect = [
                    SimpleNamespace(status='completed', output_parsed=Interpretation(intent='PHOTO_QUESTION', language='en')),
                    SimpleNamespace(status='completed', output_parsed=output)]
                result = self.follow('Is it good?')
                self.assertEqual(result['provider_status'], 'reply_unavailable')
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)
        self.assertEqual(Ticket.objects.count(), 0)

    @override_settings(DJANGO_ENV='test')
    def test_runtime_trace_disabled_outside_development(self):
        self.start()
        with patch('conversations.services.trace_logger.info') as log:
            self.follow('Is it good?')
            log.assert_not_called()


class RuntimeCommandTests(SimpleTestCase):
    @override_settings(AI_PROVIDER='openai', OPENAI_API_KEY='do-not-log-this', OPENAI_MODEL='gpt-4.1-mini')
    def test_command_no_external_calls_and_no_key(self):
        output = StringIO()
        with patch('conversations.ai.OpenAI') as sdk:
            call_command('ai_runtime', stdout=output)
            sdk.assert_not_called()
        self.assertNotIn('do-not-log-this', output.getvalue())
        self.assertTrue(json.loads(output.getvalue())['key_configured'])
