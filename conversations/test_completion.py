"""Entrega humana y finalización de investigación, sin servicios externos."""
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from . import test_progress
from .context import conversation_context
from tickets.models import Ticket


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo',CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class CompletionTests(TestCase):
    setUp=test_progress.ProgressTests.setUp
    select=test_progress.ProgressTests.select
    send=test_progress.ProgressTests.send
    def start(self):
        from .models import Conversation
        self.select('en')
        response=self.send("I don't have Internet.")
        self.assertEqual(response.status_code,200,response.content)
        self.conversation=Conversation.objects.get(pk=response.json()['conversation_id'])
    follow=test_progress.ProgressTests.follow
    post=test_progress.ProgressTests.post
    private_storage=test_progress.ProgressTests.private_storage

    def test_one_photo_and_structured_reports_complete_investigation(self):
        self.private_storage(); self.start()
        self.post('',conversation_id=self.conversation.pk)
        for text in ['The yellow cable comes from the PoE injector and is connected to the Internet port.',
                     'The other cable is connected to Ethernet port 3.',
                     'The lights are green and orange.',
                     'The PoE connects to the outdoor antenna and then to my router.']:
            self.follow(text)
        result=self.follow('I already gave you all the information I have.')
        self.assertIsNotNone(result['ticket'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),2)
        state=conversation_context(self.conversation)
        self.assertGreaterEqual(len(state['supplied_evidence']),3)
        self.assertTrue(state['evidence_exhausted'])
        self.assertFalse(state['trusted_verified_checks'])
        self.proof=[{'sender':m.sender,'text':m.content,'intent':m.metadata.get('intent'),
            'provenance':m.metadata.get('provenance')} for m in self.conversation.messages.order_by('pk')]

    def test_explicit_human_handoff_is_terminal_and_deduplicated(self):
        self.start()
        result=self.follow('I need a human.')
        self.assertIsNotNone(result['ticket'])
        number=result['ticket']['number']
        self.assertEqual(conversation_context(self.conversation)['workflow_state'],'HANDOFF_PENDING')
        count=self.conversation.diagnostic_runs.count()
        for text in ['I still have no Internet.','Please open a support ticket.','I already answered that.']:
            result=self.follow(text)
            self.assertIn(number,result['message'])
            self.assertEqual(conversation_context(self.conversation)['pending_questions'],[])
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),count)
        self.proof=[{'sender':m.sender,'text':m.content,'intent':m.metadata.get('intent'),
            'provenance':m.metadata.get('provenance')} for m in self.conversation.messages.order_by('pk')]
        self.follow('Resume self-service troubleshooting.')
        self.assertEqual(conversation_context(self.conversation)['workflow_state'],'SELF_SERVICE')

    def test_exhaustion_alone_does_not_open_ticket(self):
        self.start(); self.follow("That's all I know.")
        self.assertEqual(Ticket.objects.count(),0)

    def test_handoff_failure_never_claims_created_ticket(self):
        self.start()
        with patch('conversations.services.escalate_diagnostic',side_effect=ValidationError('Unavailable')):
            result=self.follow('I need a human.')
        self.assertIsNone(result['ticket'])
        self.assertEqual(Ticket.objects.count(),0)
        self.assertNotEqual(conversation_context(self.conversation)['workflow_state'],'HANDOFF_PENDING')

    def test_provider_failure_does_not_block_explicit_authorized_handoff(self):
        from .ai import ProviderError
        self.start()
        with patch('conversations.services.get_provider',side_effect=ProviderError('timeout')):
            result=self.follow('I need a human.')
        self.assertIsNotNone(result['ticket'])
        self.assertEqual(result['provider_status'],'unavailable')
        self.assertEqual(conversation_context(self.conversation)['workflow_state'],'HANDOFF_PENDING')

    def test_voluntary_help_does_not_restart_measurements_or_questions(self):
        from .ai import Interpretation
        self.start(); self.follow('I need a human.')
        count=self.conversation.diagnostic_runs.count()
        with override_settings(AI_PROVIDER='openai'),patch('conversations.services.get_provider') as factory:
            factory.return_value.interpret.return_value=Interpretation(intent='EXPLAIN_POE',language='en',support_help_requested=True)
            factory.return_value.generate_reply.return_value={'answer':'PoE carries compatible device power over Ethernet. Your confirmed ticket remains open for technical review.'}
            result=self.follow('What does PoE mean?')
        self.assertIn('carries',result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(),count)
        self.assertEqual(conversation_context(self.conversation)['workflow_state'],'HANDOFF_PENDING')

    def test_no_power_human_request_does_not_invent_measurements(self):
        self.select('en')
        result=self.send('My device has no power and I need a human.',language='en').json()
        self.assertIsNone(result['diagnostic'])
        self.assertIsNone(result['ticket'])
        self.assertEqual(result['requires_action'],'CONTACT_DEMO_OPERATOR')
