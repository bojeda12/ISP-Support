"""Un envío lógico, privacidad, idempotencia y compensación de archivos."""
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from . import test_context, test_multimodal
from .models import Message, Conversation, ConversationPhoto, ChatTurn
from .ai import ProviderError
from .instructions import catalog, relevant_images, catalog_errors


@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo')
class CombinedTurnTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select

    def post(self,text='',photo=True,request_id=None,conversation_id=None,csrf=True):
        if not self.client.session.get('demo_session_id'): self.select('en')
        data={'request_id':str(request_id or uuid.uuid4()),'message':text,
              'conversation_id' if conversation_id else 'service_id':conversation_id or self.service.pk}
        if photo is True: data['photo']=test_multimodal.photo_file()
        elif photo: data['photo']=photo
        return self.client.post('/api/chat/turn/',data,**({'HTTP_X_CSRFTOKEN':self.csrf} if csrf else {}))

    def private_storage(self):
        directory=TemporaryDirectory(dir=Path.cwd()); self.addCleanup(directory.cleanup)
        setting=override_settings(PRIVATE_MEDIA_ROOT=Path(directory.name)); setting.enable(); self.addCleanup(setting.disable)
        return Path(directory.name)

    def test_image_and_question_one_customer_one_assistant(self):
        self.private_storage()
        with patch('conversations.photos.get_provider') as provider:
            from .ai import DemoAIProvider
            provider.return_value.analyze_photo.return_value=DemoAIProvider().analyze_photo(image=b'',mime_type='image/jpeg',language='en')
            response=self.post('Is this yellow cable plugged into the correct port?')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['intent'],'PHOTO_QUESTION')
        self.assertEqual(Message.objects.filter(sender='customer').count(),1)
        self.assertEqual(Message.objects.filter(sender='assistant').count(),1)
        self.assertEqual(ConversationPhoto.objects.count(),1)
        user=Message.objects.get(sender='customer')
        self.assertEqual(user.content,'Is this yellow cable plugged into the correct port?')
        self.assertEqual(user.photo,ConversationPhoto.objects.get())
        self.assertEqual(provider.return_value.analyze_photo.call_args.kwargs['question'],user.content)
        history=self.client.get(f'/api/conversations/{user.conversation_id}/messages/').json()['messages']
        self.assertEqual(len(history),2); self.assertIsNotNone(history[0]['photo'])
        self.assertEqual(history[0]['request_id'],response.json()['request_id'])
        image=self.client.get(history[0]['photo']['content_url']); self.assertEqual(image.status_code,200); image.close()

    def test_image_only_and_text_only_supported(self):
        self.private_storage()
        first=self.post(); self.assertEqual(first.status_code,200)
        second=self.post('Hello',photo=False,conversation_id=first.json()['conversation_id'])
        self.assertEqual(second.status_code,200)
        self.assertEqual(Message.objects.count(),4); self.assertEqual(ConversationPhoto.objects.count(),1)

    def test_idempotent_retry_no_duplicate_photos_or_messages(self):
        self.private_storage(); key=uuid.uuid4()
        first=self.post('Is it good?',request_id=key)
        second=self.post('Is it good?',request_id=key)
        self.assertEqual(first.status_code,200); self.assertEqual(first.json(),second.json())
        self.assertEqual(Message.objects.count(),2); self.assertEqual(ConversationPhoto.objects.count(),1)
        self.assertEqual(ChatTurn.objects.count(),1)
        self.assertEqual(self.post('Changed text',request_id=key).status_code,400)

    def test_unexpected_failure_rolls_back_turn_and_private_file_then_retry(self):
        root=self.private_storage(); key=uuid.uuid4()
        with patch('conversations.services.get_provider',side_effect=RuntimeError('controlled test failure')):
            with self.assertRaises(RuntimeError): self.post('Is it good?',request_id=key)
        self.assertEqual(Message.objects.count(),0); self.assertEqual(ConversationPhoto.objects.count(),0)
        self.assertEqual(Conversation.objects.count(),0); self.assertEqual(ChatTurn.objects.count(),0)
        self.assertEqual(list(root.rglob('*.jpg')),[])
        self.assertEqual(self.post('Is it good?',request_id=key).status_code,200)

    def test_invalid_image_does_not_create_partial_turn(self):
        self.private_storage()
        result=self.post('Question',photo=SimpleUploadedFile('x.png',b'<svg/>',content_type='image/png'))
        self.assertEqual(result.status_code,400)
        self.assertEqual(Message.objects.count(),0); self.assertEqual(Conversation.objects.count(),0)

    def test_csrf_and_cross_conversation_protection(self):
        self.private_storage(); self.select('en')
        self.assertEqual(self.post('Hello',csrf=False).status_code,403)
        other=Conversation.objects.create(customer=self.service.customer,internet_service=self.service)
        from customers.models import InternetService
        service=InternetService.objects.get(service_identifier='DEMO-SERVICE-002')
        self.client.post('/demo/session/',{'service_id':service.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(self.post('Question',conversation_id=other.pk).status_code,400)
        self.client.logout()
        self.assertEqual(self.client.post('/api/chat/turn/',{'message':'Question'}).status_code,401)

    def test_provider_failure_is_one_coherent_saved_turn(self):
        self.private_storage()
        with patch('conversations.photos.get_provider',side_effect=ProviderError('timeout')):
            result=self.post('Is it good?')
        self.assertEqual(result.status_code,200)
        self.assertEqual(ConversationPhoto.objects.get().status,'FAILED')
        self.assertEqual(Message.objects.count(),2)
        self.assertIn('analysis is unavailable',result.json()['message'])


class ExplicitGuideTests(TestCase):
    def test_bilingual_order_mime_and_exact_assets(self):
        self.assertEqual(catalog_errors(),[])
        for language in ('en','es'):
            images=relevant_images('CPE_UNREACHABLE',language)
            self.assertEqual([i['step_number'] for i in images],[1,2,3,4])
            self.assertEqual([i['path'] for i in images],['demo_photos/poe_locate_demo.jpg','demo_photos/poe_power_indicator_demo.jpg',
                'demo_photos/ethernet_inspection_demo.jpg',f'recheck-{language}.svg'])
            self.assertEqual([i['mime_type'] for i in images],['image/jpeg']*3+['image/svg+xml'])

    def test_other_scenarios_use_explicit_independent_guides(self):
        self.assertEqual(relevant_images('SIGNAL_DEGRADED','en'),[])
        self.assertEqual(relevant_images('SERVICE_SUSPENDED','en'),[])
        self.assertEqual([i['id'] for i in relevant_images('PERFORMANCE_DEGRADED','en')],['router-en'])

    def test_missing_photo_has_no_legacy_fallback(self):
        with patch('conversations.instructions.Path.is_file',return_value=False):
            self.assertEqual(relevant_images('CPE_UNREACHABLE','en'),[])
            self.assertTrue(catalog_errors())
