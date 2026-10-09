"""Referencias locales: rutas estables, procedencia explícita y entrega protegida."""
from io import BytesIO

from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from . import test_multimodal
from .instructions import ASSET_ROOT, catalog, relevant_images


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo')
class InstructionPhotoTests(TestCase):
    setUp = test_multimodal.MultimodalTests.setUp

    def test_stable_ids_map_to_supplied_jpegs_and_neutral_recheck(self):
        for language in ('en', 'es'):
            entries = relevant_images('CPE_UNREACHABLE', language)
            self.assertEqual([entry['id'] for entry in entries],
                [f'{topic}-{language}' for topic in ('poe', 'lights', 'ethernet', 'recheck')])
            self.assertEqual([entry['path'] for entry in entries[:3]], [
                'demo_photos/poe_locate_demo.jpg',
                'demo_photos/poe_power_indicator_demo.jpg',
                'demo_photos/ethernet_inspection_demo.jpg'])
            self.assertEqual(entries[3]['path'], f'recheck-{language}.svg')
            self.assertEqual(entries[3]['mime_type'], 'image/svg+xml')
            self.assertTrue(all(entry['url'] == f"/api/instructions/{entry['id']}/" for entry in entries))

    def test_jpeg_delivery_preserves_authorization_and_security_headers(self):
        anonymous = APIClient()
        for language in ('en', 'es'):
            for item in catalog(language):
                self.assertEqual(anonymous.get(item['url']).status_code, 401)
                response = self.client.get(item['url'])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], item['mime_type'])
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertIn('sandbox', response['Content-Security-Policy'])
                content = b''.join(response.streaming_content)
                response.close()
                self.assertEqual(content, (ASSET_ROOT/item['path']).read_bytes())
                if item['mime_type'] == 'image/jpeg':
                    with Image.open(BytesIO(content)) as image:
                        self.assertEqual(image.format, 'JPEG')
                        self.assertFalse(image.getexif())

    def test_bilingual_disclosures_do_not_claim_hardware_verification(self):
        for language in ('en', 'es'):
            entries = relevant_images('CPE_UNREACHABLE', language)
            for item in entries[:3]:
                self.assertEqual(item['source'], 'supplied_ai_generated_demo')
                self.assertFalse(item['production_approved'])
                self.assertIsNone(item['verified_model'])
                self.assertNotEqual(item['license'], 'CC0-1.0')
                self.assertIn(item['caption'], item['description'])
                self.assertEqual(item['descriptions'][language], item['description'])
                self.assertIn('AI-generated' if language == 'en' else 'generado con IA', item['alt_text'])
            self.assertIn('not the same' if language == 'en' else 'no es lo mismo', entries[0]['description'])
            self.assertIn('does not prove' if language == 'en' else 'no demuestra', entries[1]['description'])

    def test_no_raw_file_or_reference_infographic_endpoint(self):
        for path in ('/api/instructions/reference_infographic/',
                     '/api/instructions/poe_locate_demo.jpg/',
                     '/static/conversations/instruction_assets/demo_photos/poe_locate_demo.jpg'):
            self.assertEqual(self.client.get(path).status_code, 404)
