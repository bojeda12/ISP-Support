"""Respuestas breves, RAG observable y fallos controlados sin llamadas externas."""
from unittest.mock import patch
from types import SimpleNamespace
from django.test import override_settings, SimpleTestCase
from pydantic import ValidationError
from .test_knowledge_chat import KnowledgeChatIntegrationTests
from .ai import ConversationalReply, Interpretation, ProviderError
from .ai import OpenAIProvider
from .short_answers import short_answer


class ShortAnswerTests(KnowledgeChatIntegrationTests):
    # Reutilizar fixtures; también conserva las regresiones de RAG heredadas.
    def test_three_short_questions_retrieve_and_cite_locally(self):
        self.reference()
        for message, intent, fragment in [('is it good?', 'PHOTO_QUESTION','physical connection'),
                ('yellow wire is green and orange','REPORT_INDICATORS','negotiated speed'),
                ('is this device','EQUIPMENT_CLARIFICATION','separate PoE injector')]:
            result=self.post(message).json()
            self.assertEqual(result['intent'],intent)
            self.assertIn(fragment,result['message'])
            self.assertTrue(result['debug']['knowledge']['retrieval_attempted'])
            self.assertFalse(result['debug']['knowledge']['context_injected'])
            self.assertNotIn('approved instructions are unavailable',result['message'])

    def test_retrieval_failure_answers_led_question(self):
        with patch('knowledge.services.retrieve',side_effect=RuntimeError('not logged')):
            result=self.post('yellow wire is green and orange',photo=False).json()
        self.assertIn('negotiated speed',result['message'])
        self.assertEqual(result['debug']['chat']['fallback_reason'],'retrieval_error')
        self.assertFalse(result['debug']['knowledge']['retrieval_succeeded'])
        self.assertEqual(result['citations'],[])

    def test_provider_failure_uses_photo_and_question(self):
        self.reference()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as provider:
            provider.return_value.interpret.return_value=Interpretation(intent='PHOTO_QUESTION',language='en')
            provider.return_value.generate_reply.side_effect=ProviderError('timeout')
            result=self.post('is it good?',photo=False).json()
        self.assertIn('physical connection',result['message'])
        self.assertIn('What label',result['message'])
        self.assertNotIn('temporarily unavailable',result['message'])
        self.assertEqual(result['debug']['chat']['fallback_reason'],'timeout')
        self.assertTrue(result['citations'])

    def test_no_document_remains_useful(self):
        result=self.post('is this device').json()
        self.assertIn('router/modem/gateway',result['message'])
        self.assertIn('without its exact model',result['message'])
        self.assertFalse(result['debug']['knowledge']['retrieval_succeeded'])
        self.assertEqual(result['citations'],[])

    def test_observations_are_used_without_invented_identity(self):
        context={'photo':{'status':'COMPLETED','simulated':False,'observations':['A gateway-shaped enclosure with Ethernet ports is visible.']},'diagnostic':None}
        text=short_answer('is this device',context,'en','EQUIPMENT_CLARIFICATION')
        self.assertIn('gateway-shaped',text)
        self.assertEqual(text.count('?'),1)


class ReplyValidationTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY='mock-only',OPENAI_MODEL='gpt-4.1-mini')
    def test_incomplete_output_has_a_specific_safe_reason(self):
        with patch('conversations.ai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.parse.return_value=SimpleNamespace(status='incomplete',output_parsed=None)
            with self.assertRaisesRegex(ProviderError,'output_incomplete'):
                OpenAIProvider().generate_reply(message='is it good?',context={},language='en',intent='PHOTO_QUESTION',focus='connections')

    def test_negative_warning_is_allowed_but_action_after_warning_rejected(self):
        ConversationalReply(answer='Observe the lights without unplugging cables.')
        with self.assertRaises(ValidationError):
            ConversationalReply(answer='Do not unplug the cable, but reset the router.')
