"""Regresiones de memoria y formatos; proveedores externos siempre simulados."""
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from tickets.models import Ticket
from . import test_context, test_multimodal
from .ai import Interpretation
from .context import conversation_context
from .models import Conversation, ConversationPhoto, Message
from .visual_schema import VisualAnalysis


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo')
class MemoryTests(TestCase):
    setUp = test_context.ContextTests.setUp
    select = test_context.ContextTests.select
    send = test_context.ContextTests.send
    start = test_context.ContextTests.start
    follow = test_context.ContextTests.follow
    upload = test_context.ContextTests.upload

    def analyzed_photo(self, observations, uncertainties=None):
        with patch('conversations.photos.get_provider') as factory:
            factory.return_value.analyze_photo.return_value = VisualAnalysis(
                observations=observations, uncertainties=uncertainties or ['Device model is uncertain.'],
                recommended_actions=['CHECK_INDICATORS'], connectivity_confirmed=False)
            response = self.upload()
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_contracted_no_internet_starts_authorized_diagnostic(self):
        self.select('en')
        result = self.send("I don't have Internet.").json()
        self.assertEqual(result['diagnostic']['result_code'], 'CPE_UNREACHABLE')
        self.assertEqual(len(result['images']), 4)

    def test_direct_question_uses_one_relevant_observation_without_full_report(self):
        self.start()
        self.analyzed_photo(['A green power indicator is visible.', 'A black enclosure is visible.', 'A table is visible.'])
        result = self.follow('Is this good?')
        self.assertEqual(result['intent'], 'PHOTO_QUESTION')
        self.assertIn('cannot confirm whether this is normal', result['message'])
        self.assertIn('green power indicator', result['message'])
        self.assertNotIn('black enclosure', result['message'])
        self.assertIn('cannot reach the outdoor equipment', result['message'])
        self.assertLess(len(result['message']), 650)
        self.assertEqual(result['images'], [])

    def test_second_question_does_not_repeat_photo_report(self):
        self.start()
        self.analyzed_photo(['A green power indicator is visible.'])
        self.follow('Is this good?')
        result = self.follow('What does that light mean?')
        self.assertNotIn('green power indicator', result['message'])
        self.assertIn('model manual', result['message'])
        self.assertEqual(self.conversation.diagnostic_runs.count(), 1)

    def test_front_and_back_saved_observations_without_assuming_device_identity(self):
        self.start()
        self.analyzed_photo(['A front power light is visible.'])
        self.analyzed_photo(['Rear Ethernet connections are visible.'])
        result = self.follow('What about the back?')
        self.assertEqual(result['intent'], 'PHOTO_COMPARISON')
        self.assertIn('Rear Ethernet', result['message'])
        self.assertIn('front power light', result['message'])
        self.assertIn('cannot confirm both photos show the same device', result['message'])
        self.assertIn('not a fresh image comparison', result['message'])

    def test_only_three_photos_in_memory_and_latest_is_explicit(self):
        self.start()
        for index in range(5):
            self.analyzed_photo([f'View number {index}.'])
        context = conversation_context(self.conversation)
        self.assertEqual(len(context['photos']), 3)
        self.assertEqual(context['photo']['observations'], ['View number 4.'])
        self.assertNotIn('View number 0', str(context))
        self.assertEqual(context['service_id'], self.service.pk)

    def test_latest_failed_analysis_cannot_reuse_older_observations_as_latest(self):
        self.start()
        self.analyzed_photo(['An earlier light is green.'])
        with patch('conversations.photos.get_provider') as factory:
            factory.return_value.analyze_photo.return_value = {'invalid': True}
            self.assertEqual(self.upload().json()['status'], 'FAILED')
        result = self.follow('Is this good?')
        self.assertIn('latest photo analysis is unavailable', result['message'])
        self.assertNotIn('earlier light is green', result['message'])

    def test_model_answer_is_remembered_without_repeating_question(self):
        self.start()
        self.follow("It's a Frontier router.")
        result = self.follow('NVG468MQ')
        self.assertEqual(result['intent'], 'ANSWER_CLARIFICATION')
        result = self.follow("It's a Frontier router.")
        self.assertNotIn('What exact model', result['message'])
        context = conversation_context(self.conversation)
        self.assertEqual(context['answered_questions'][-1]['answer'], 'NVG468MQ')
        self.assertFalse(context['answered_questions'][-1]['verified'])
        self.assertNotIn('equipment_model', context['unresolved_questions'])

    def test_equipment_description_containing_model_does_not_request_model_again(self):
        self.start()
        result = self.follow("It's an Arris NVG468MQ router.")
        self.assertNotIn('What exact model', result['message'])
        self.assertTrue(conversation_context(self.conversation)['answered_questions'])

    def test_indicator_answer_is_not_repeated(self):
        self.start()
        self.follow('All the lights are green.')
        self.assertEqual(self.follow('Power LED')['intent'], 'ANSWER_CLARIFICATION')
        self.assertNotIn('Which labeled indicator', self.follow('All the lights are green.')['message'])

    def test_completed_checks_survive_many_turns_and_refresh_with_one_ticket(self):
        self.start()
        result = self.follow('I already checked the cables.')
        number = result['ticket']['number']
        for _ in range(10):
            self.follow('All the lights are green.')
        history = self.client.get(f'/api/conversations/{self.conversation.pk}/messages/')
        self.assertEqual(history.status_code, 200)
        context = conversation_context(Conversation.objects.get(pk=self.conversation.pk))
        self.assertTrue(context['completed_checks'])
        self.assertFalse(context['completed_checks'][0]['verified'])
        result = self.follow("I still don't have Internet.")
        self.assertIn(number, result['message'])
        self.assertEqual(result['images'], [])
        self.assertEqual(Ticket.objects.count(), 1)

    def test_spanish_questions_and_switching_do_not_repeat_guide(self):
        self.start()
        self.analyzed_photo(['Se observa una luz encendida.'], ['No se conoce su significado.'])
        result = self.follow('¿Está bien?')
        self.assertEqual(result['language'], 'es')
        self.assertIn('No puedo confirmar', result['message'])
        result = self.follow('¿Y la parte trasera?')
        self.assertEqual(result['intent'], 'PHOTO_COMPARISON')
        self.assertIn('Solo tengo una vista', result['message'])
        result = self.follow('Todavía no tengo Internet')
        self.assertEqual(result['images'], [])
        self.assertEqual(self.follow('Show the guide again')['language'], 'en')

    def test_provider_gets_compact_history_and_persistent_observation_summaries(self):
        self.start()
        self.analyzed_photo(['A light is visible.'])
        with patch('conversations.services.get_provider') as factory:
            def interpret(**kwargs):
                self.assertLessEqual(len(kwargs['history']), 5)
                self.assertLessEqual(sum(len(v['content']) for v in kwargs['history']), 2000)
                self.assertEqual(kwargs['history'][0]['context']['photo']['observations'], ['A light is visible.'])
                return Interpretation(intent='PHOTO_QUESTION', language='en')
            factory.return_value.interpret.side_effect = interpret
            self.follow('Is this good?')


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo')
class ExtendedUploadTests(TestCase):
    setUp = test_multimodal.MultimodalTests.setUp
    upload = test_multimodal.MultimodalTests.upload

    def webp(self, name='photo.webp', content_type='image/webp', animated=False):
        output = BytesIO()
        image = Image.new('RGB', (40, 30), 'green')
        kwargs = {'save_all': True, 'append_images': [Image.new('RGB', (40,30), 'red')]} if animated else {}
        image.save(output, format='WEBP', **kwargs)
        return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)

    def test_webp_is_normalized_to_private_jpeg(self):
        with patch('conversations.photos.get_provider') as factory:
            factory.return_value.analyze_photo.return_value = VisualAnalysis(observations=[],
                uncertainties=['Unknown'], recommended_actions=['CONTACT_SUPPORT'], connectivity_confirmed=False)
            response = self.upload(self.webp())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['mime_type'], 'image/jpeg')
        sent = factory.return_value.analyze_photo.call_args.kwargs
        self.assertEqual(sent['mime_type'], 'image/jpeg')
        with Image.open(BytesIO(sent['image'])) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertFalse(image.getexif())
        download = self.client.get(response.json()['content_url'])
        self.assertEqual(download['Cache-Control'], 'private, no-store')
        download.close()

    def test_heic_heif_clear_fallback_without_provider_calls(self):
        for extension in ('heic', 'heif'):
            with patch('conversations.photos.get_provider') as factory:
                response = self.upload(SimpleUploadedFile('photo.'+extension,
                    b'heif fixture not decoded', content_type='image/'+extension))
                self.assertEqual(response.status_code, 400)
                self.assertIn('Export the photo as JPEG', response.json()['photo'])
                factory.assert_not_called()
        self.assertEqual(ConversationPhoto.objects.count(), 0)

    def test_webp_spoofed_corrupt_and_animated_rejected(self):
        for file in (self.webp('photo.png','image/png'), self.webp(animated=True),
                     SimpleUploadedFile('fake.webp',b'<svg/>',content_type='image/webp'),
                     SimpleUploadedFile('fake.webp',self.webp().read()[:25],content_type='image/webp')):
            self.assertEqual(self.upload(file).status_code, 400)
        self.assertEqual(ConversationPhoto.objects.count(), 0)

    @override_settings(PHOTO_MAX_PIXELS=100)
    def test_webp_decoded_limits_apply(self):
        self.assertEqual(self.upload(self.webp()).status_code, 400)

    @override_settings(PHOTO_MAX_BYTES=100)
    def test_webp_encoded_size_limit_before_provider(self):
        file = SimpleUploadedFile('large.webp',b'x'*101,content_type='image/webp')
        self.assertEqual(self.upload(file).status_code, 413)

    def test_jpeg_orientation_remains_corrected_without_exif(self):
        output = BytesIO()
        image = Image.new('RGB',(40,30),'blue')
        exif=image.getexif(); exif[274]=6
        image.save(output,format='JPEG',exif=exif)
        result=self.upload(SimpleUploadedFile('photo.jpeg',output.getvalue(),content_type='image/jpeg')).json()
        self.assertEqual((result['width'],result['height']),(30,40))
        photo=ConversationPhoto.objects.get(pk=result['id'])
        from .photos import photo_storage
        with photo_storage().open(photo.storage_key) as file:
            self.assertFalse(Image.open(file).getexif())
