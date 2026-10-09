"""Regresiones de seguimiento con sesiones, CSRF y proveedores sin llamadas externas."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from diagnostics.models import DiagnosticRun
from tickets.models import Ticket
from . import test_language_ux, test_multimodal
from .ai import DemoAIProvider, Interpretation, OpenAIProvider, ProviderError
from .context import conversation_context
from .models import Conversation, Message
from .visual_schema import VisualAnalysis


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo')
class ContextTests(TestCase):
    setUp = test_language_ux.LanguageUXTests.setUp
    select = test_language_ux.LanguageUXTests.select
    send = test_language_ux.LanguageUXTests.send

    def start(self):
        self.select('en')
        result = self.send('No Internet').json()
        self.conversation = Conversation.objects.get(pk=result['conversation_id'])
        return result

    def follow(self, text):
        response = self.send(text, self.conversation.pk)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def upload(self):
        directory = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        return self.client.post(f'/api/conversations/{self.conversation.pk}/photos/',
            {'photo': test_multimodal.photo_file()}, HTTP_X_CSRFTOKEN=self.csrf)

    def test_equipment_clarification_preserves_issue_and_distinctions(self):
        self.start()
        result = self.follow("It's a Frontier router.")
        self.assertEqual(result['intent'], 'EQUIPMENT_CLARIFICATION')
        self.assertIn('different from a PoE injector', result['message'])
        self.assertIn('CPE_UNREACHABLE', result['message'])
        context = conversation_context(self.conversation)
        self.assertEqual(context['reported_issue'], 'NO_INTERNET')
        self.assertFalse(context['equipment_claim']['verified'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)

    def test_realistic_mocked_photo_observations_reach_subsequent_provider(self):
        self.start()
        analysis = VisualAnalysis(observations=['A green indicator is visible on a gateway.'],
            uncertainties=['The model and meaning of this light are unclear.'],
            recommended_actions=['CHECK_INDICATORS'], connectivity_confirmed=False)
        with patch('conversations.photos.get_provider') as factory:
            factory.return_value.analyze_photo.return_value = analysis
            self.assertEqual(self.upload().status_code, 201)
        with patch('conversations.services.get_provider') as factory:
            def interpret(**kwargs):
                context = kwargs['history'][0]['context']
                self.assertIn('green indicator', context['photo']['observations'][0])
                self.assertFalse(context['photo']['connectivity_confirmed'])
                self.assertNotIn('storage_key', json.dumps(context))
                return Interpretation(intent='PHOTO_QUESTION', language='en')
            factory.return_value.interpret.side_effect = interpret
            result = self.follow('What does that light mean?')
        self.assertIn('green indicator', result['message'])
        self.assertIn('unclear', result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_demo_photo_is_not_mistaken_for_visual_recognition(self):
        self.start()
        self.assertEqual(self.upload().status_code, 201)
        result = self.follow('What does that light mean?')
        self.assertIn('simulated', result['message'])
        self.assertIn('not interpreted', result['message'])
        self.assertIn('model', result['message'])

    def test_green_lights_neither_verify_recovery_nor_complete_checks(self):
        self.start()
        result = self.follow('All the lights are green.')
        self.assertEqual(result['intent'], 'REPORT_INDICATORS')
        self.assertIn('do not prove outdoor CPE connectivity', result['message'])
        self.assertIn('simulated diagnostic reports CPE_UNREACHABLE', result['message'])
        self.assertFalse(conversation_context(self.conversation)['customer_claims'][-1]['verified'])
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)

    def test_repeated_problem_does_not_repeat_guide_or_diagnostic_instructions(self):
        first = self.start()
        self.assertEqual(len(first['images']), 4)
        result = self.follow('I still have no Internet.')
        self.assertEqual(result['images'], [])
        self.assertNotIn('Check the PoE injector', result['message'])
        self.assertNotIn('Check the PoE injector', result['diagnostic']['explanation'])
        explicit = self.follow('Show the guide again')
        self.assertEqual(len(explicit['images']), 4)
        self.assertEqual(self.conversation.diagnostic_runs.count(), 2)

    def test_unknown_injector_and_equipment_mismatch_ask_useful_questions(self):
        self.start()
        result = self.follow("I don't know what a PoE injector is.")
        self.assertEqual(result['intent'], 'EXPLAIN_POE')
        self.assertIn('separate adapter', result['message'])
        self.assertEqual(len(result['images']), 1)
        result = self.follow("That's not the device I have.")
        self.assertEqual(result['intent'], 'EQUIPMENT_CLARIFICATION')
        self.assertIn('exact model', result['message'])
        self.assertEqual(result['images'], [])

    def test_ambiguous_completed_claim_clarifies_without_escalating(self):
        self.start()
        result = self.follow('I already tried that.')
        self.assertEqual(result['intent'], 'CLARIFY_COMPLETED_CHECKS')
        self.assertIn('Which accessible checks', result['message'])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_confirmation_escalates_and_later_turns_keep_one_ticket(self):
        self.start()
        self.follow('All the lights are green.')
        result = self.follow('I checked all accessible connections and the lights are green.')
        self.assertEqual(result['ticket']['status'], 'OPEN')
        self.assertEqual(result['images'], [])
        self.assertIn('Thank you', result['message'])
        number = result['ticket']['number']
        for text in ['I still have no Internet.', "It's a Frontier router.", 'I checked the cables']:
            result = self.follow(text)
            self.assertIn(number, result['message'])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertNotIn('reports checking PoE', Ticket.objects.get().description)

    def test_typos_and_adaptive_spanish_keep_context(self):
        self.select('en')
        result = self.send('My interent is not working.').json()
        self.assertEqual(result['intent'], 'NO_INTERNET')
        self.conversation = Conversation.objects.get(pk=result['conversation_id'])
        result = self.follow('Las lueces estan verdes')
        self.assertEqual(result['intent'], 'REPORT_INDICATORS')
        self.assertEqual(result['language'], 'es')
        result = self.follow('Ya revisé los cables pero no funcina')
        self.assertEqual(result['intent'], 'CONFIRM_PHYSICAL_CHECK')
        self.assertEqual(result['ticket']['status'], 'OPEN')

    def test_contextual_fallback_photo_request_and_provider_failure(self):
        self.start()
        self.assertIn('still working', self.follow('The other one over there')['message'])
        self.assertIn('JPEG or PNG', self.follow('Can I send you another picture?')['message'])
        before = DiagnosticRun.objects.count()
        with patch('conversations.services.get_provider', side_effect=ProviderError('timeout')):
            result = self.follow('I checked the cables')
        self.assertEqual(result['provider_status'], 'unavailable')
        self.assertEqual(DiagnosticRun.objects.count(), before)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(conversation_context(self.conversation)['reported_issue'], 'NO_INTERNET')

    def test_context_bounded_and_ticket_status_refreshed_from_database(self):
        self.start()
        self.follow('I checked the cables')
        Ticket.objects.update(status='IN_PROGRESS')
        for index in range(12):
            self.follow("It's a Frontier router. " + str(index) + 'x' * 500)
        context = conversation_context(self.conversation)
        self.assertLessEqual(len(context['customer_claims']), 8)
        self.assertLessEqual(len(context['shown_guides']), 20)
        self.assertEqual(context['ticket']['status'], 'IN_PROGRESS')
        self.assertLess(len(json.dumps(context)), 8000)

    def test_language_switch_after_ticket_does_not_restart_completed_guide(self):
        self.start()
        self.follow('I checked the cables')
        result = self.follow('Todavía no tengo Internet')
        self.assertEqual(result['language'], 'es')
        self.assertEqual(result['images'], [])
        self.assertIn('No necesitas repetir', result['message'])
        self.assertEqual(Ticket.objects.count(), 1)

    def test_existing_state_does_not_hide_first_guide_for_new_diagnostic(self):
        from diagnostics.services import set_demo_scenario
        self.start()
        set_demo_scenario(internet_service=self.service, scenario='LOW_THROUGHPUT')
        result = self.follow('My internet is slow')
        self.assertTrue(result['images'])

    @override_settings(OPENAI_API_KEY='mock-only', OPENAI_MODEL='mock-model')
    def test_official_adapter_receives_structured_context_without_external_call(self):
        self.start()
        context = conversation_context(self.conversation)
        with patch('conversations.ai.OpenAI') as factory:
            parse = factory.return_value.__enter__.return_value.responses.parse
            parse.return_value = SimpleNamespace(status='completed', output_parsed=Interpretation(intent='EQUIPMENT_CLARIFICATION', language='en'))
            result = OpenAIProvider().interpret(message="It's a Frontier router.",
                history=[{'role': 'context', 'content': '', 'context': context}], language='en')
        self.assertEqual(result.intent, 'EQUIPMENT_CLARIFICATION')
        self.assertEqual(json.loads(parse.call_args.kwargs['input'])['history'][0]['context']['reported_issue'], 'NO_INTERNET')
        self.assertFalse(parse.call_args.kwargs['store'])
