"""Prueba integral de evidencia documental, visión y texto; OpenAI siempre simulado."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from knowledge.tests import pdf_bytes
from knowledge.models import ReferenceDocument
from knowledge.services import ingest, approve
from . import test_context, test_combined_turns
from .ai import Interpretation, REPLY_INSTRUCTIONS
from .visual_schema import VisualAnalysis
from .models import Message


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo')
class KnowledgeChatIntegrationTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select
    post = test_combined_turns.CombinedTurnTests.post
    private_storage = test_combined_turns.CombinedTurnTests.private_storage

    def reference(self):
        self.private_storage()
        doc=ReferenceDocument(code='integration',title='Reviewed generic equipment reference',revision='1',source='Fictional test PDF',customer_safe=True,visibility=ReferenceDocument.Visibility.CUSTOMER)
        doc.pdf.save('reference.pdf',SimpleUploadedFile('reference.pdf',pdf_bytes(['Inspect accessible Ethernet connectors visually. A light does not prove Internet access.'])),save=False)
        doc.save(); ingest(doc); doc.sections.update(approved_for_chat=True); approve(doc)
        return doc

    def test_demo_uses_actual_indexed_pdf_with_page_and_disclaimer(self):
        doc=self.reference()
        result=self.post('Are these Ethernet cables connected correctly?').json()
        self.assertNotIn('Inspect accessible Ethernet connectors visually.',result['message'])
        self.assertIn(doc.title,result['message']); self.assertNotIn('p. 1',result['message'])
        self.assertIn('Visually check accessible Ethernet',result['message'])
        self.assertIn('not interpreted',result['message'])
        self.assertEqual(result['citations'][0]['document_id'],str(doc.pk))
        assistant=Message.objects.get(sender='assistant')
        self.assertEqual(assistant.metadata['knowledge']['usage'],'cited')

    def test_approved_authorized_excerpts_reach_real_adapter_path(self):
        doc=self.reference(); doc.allow_external_ai=True; doc.save()
        section=doc.sections.first()
        quote='Inspect accessible Ethernet connectors visually.'
        with override_settings(AI_PROVIDER='openai',OPENAI_API_KEY='mock-only',OPENAI_MODEL='gpt-4.1-mini',OPENAI_VISION_MODEL='gpt-4.1-mini',KNOWLEDGE_ALLOW_EXTERNAL_AI=True),patch('conversations.ai.OpenAI') as sdk:
            client=sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect=[
                SimpleNamespace(status='completed',output_parsed=VisualAnalysis(observations=['An Ethernet plug is visible.'],uncertainties=['Port purpose is unknown.'],recommended_actions=['CHECK_INDICATORS'],connectivity_confirmed=False)),
                SimpleNamespace(status='completed',output_parsed=Interpretation(intent='PHOTO_QUESTION',language='en',photo_focus='connections')),
                SimpleNamespace(status='completed',output_parsed={'answer':'The visible plug suggests a physical connection, but cannot establish Internet access. Observe accessible connectors and the labeled link indicator.',
                    'citations':[{'section_id':str(section.pk),'quote':quote}]})]
            result=self.post('Are these Ethernet cables connected correctly?').json()
            calls=client.responses.parse.call_args_list
            self.assertEqual(len(calls),3)
            self.assertIn('Are these Ethernet cables',calls[0].kwargs['input'][0]['content'][0]['text'])
            self.assertIn(section.text,calls[2].kwargs['input'])
            self.assertIn('untrusted reference DATA',calls[2].kwargs['instructions'])
        self.assertEqual(Message.objects.get(sender='assistant').metadata['citations'][0]['quote'],quote)
        self.assertNotIn('p. 1',result['message'])
        self.assertEqual(Message.objects.get(sender='assistant').metadata['provenance']['response_source'],'openai_generated')

    def test_unauthorized_document_excerpts_never_leave_backend(self):
        doc=self.reference(); section=doc.sections.first()
        with override_settings(AI_PROVIDER='openai',OPENAI_API_KEY='mock-only',OPENAI_MODEL='gpt-4.1-mini',KNOWLEDGE_ALLOW_EXTERNAL_AI=True),patch('conversations.ai.OpenAI') as sdk:
            client=sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect=[SimpleNamespace(status='completed',output_parsed=Interpretation(intent='PHOTO_QUESTION',language='en')),
                SimpleNamespace(status='completed',output_parsed={'answer':'Inspect the accessible connector visually; equipment-specific instructions are unavailable.'})]
            result=self.post('Are the Ethernet cables connected?',photo=False).json()
            self.assertNotIn(section.text,client.responses.parse.call_args.kwargs['input'])
        self.assertTrue(result['citations'])
        self.assertEqual(Message.objects.get(sender='assistant').metadata['knowledge']['citation_origin'],'django_local')
        self.assertFalse(result['debug']['knowledge']['context_injected'])

    def test_fabricated_citation_is_rejected_and_not_displayed(self):
        doc=self.reference(); doc.allow_external_ai=True; doc.save()
        with override_settings(AI_PROVIDER='openai',OPENAI_API_KEY='mock-only',OPENAI_MODEL='gpt-4.1-mini',KNOWLEDGE_ALLOW_EXTERNAL_AI=True),patch('conversations.ai.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.parse.side_effect=[
                SimpleNamespace(status='completed',output_parsed=Interpretation(intent='PHOTO_QUESTION',language='en')),
                SimpleNamespace(status='completed',output_parsed={'answer':'According to the manual, use port seven.',
                    'citations':[{'section_id':str(doc.sections.first().pk),'quote':'Use port seven.'}]})]
            result=self.post('Are the Ethernet cables connected?',photo=False).json()
        self.assertEqual(result['provider_status'],'reply_unavailable')
        self.assertTrue(all('port seven' not in item['quote'] for item in Message.objects.get(sender='assistant').metadata['citations']))
        self.assertNotIn('Use port seven.',result['message'])
        self.assertNotIn('port seven',result['message'])
