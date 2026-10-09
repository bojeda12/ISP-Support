import os
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, sentinel

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from openai import APITimeoutError
from PIL import Image
from rest_framework.test import APIClient

from config.env_loading import load_development_env
from diagnostics.models import DiagnosticRun
from tickets.models import Ticket
from .ai import OpenAIProvider, ProviderError
from .demo_sessions import issue_demo_session
from .instructions import ASSET_ROOT, catalog
from .models import Conversation, ConversationPhoto, Message
from .photos import photo_storage
from .visual_schema import VisualAnalysis
from customers.models import InternetService


def photo_file(name="photo.png", format="PNG", size=(40, 30)):
    output = BytesIO()
    image = Image.new("RGB", size, "blue")
    if format == "JPEG":
        exif = image.getexif()
        exif[270] = "Private metadata that must be removed"
        image.save(output, format=format, exif=exif)
    else:
        image.save(output, format=format)
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/jpeg" if format == "JPEG" else "image/png")


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV="development", AI_PROVIDER="demo")
class MultimodalTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=settings.BASE_DIR)
        self.addCleanup(self.directory.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)
        call_command("seed_demo", stdout=StringIO())
        self.service = InternetService.objects.get(service_identifier="DEMO-SERVICE-001")
        self.user = get_user_model().objects.create_user(username="photo-operator", is_staff=True)
        self.user.user_permissions.add(Permission.objects.get(codename="use_demo_chat"))
        self.session, token = issue_demo_session(operator=self.user, internet_service=self.service)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Demo {token}")
        self.conversation = Conversation.objects.create(customer=self.service.customer, internet_service=self.service)
        self.url = reverse("api:conversation-photos", args=[self.conversation.pk])

    def upload(self, file=None):
        return self.client.post(self.url, {"photo": file or photo_file()}, format="multipart")

    def test_demo_analysis_is_explicit_and_never_confirms_connectivity(self):
        diagnostics_before = DiagnosticRun.objects.count()
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["simulated"])
        self.assertEqual(data["status"], "COMPLETED")
        self.assertIn("SIMULADO", data["analysis"]["observations"][0])
        self.assertTrue(data["analysis"]["uncertainties"])
        self.assertIs(data["analysis"]["connectivity_confirmed"], False)
        self.assertEqual(DiagnosticRun.objects.count(), diagnostics_before)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 2)
        self.assertNotIn("storage_key", data)

    def test_private_content_and_metadata_roundtrip(self):
        data = self.upload().json()
        response = self.client.get(data["content_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        content = b"".join(response.streaming_content)
        response.close()
        self.assertEqual(Image.open(BytesIO(content)).size, (40, 30))
        detail = self.client.get(reverse("api:photo-detail", args=[data["id"]]))
        self.assertEqual(detail.json()["id"], data["id"])
        self.assertEqual(len(self.client.get(self.url).json()["photos"]), 1)
        with self.assertRaises(ValueError):
            photo_storage().url("photos/test.jpg")

    def test_exif_is_removed(self):
        data = self.upload(photo_file("photo.jpg", "JPEG")).json()
        photo = ConversationPhoto.objects.get(pk=data["id"])
        with photo_storage().open(photo.storage_key) as file:
            self.assertEqual(len(Image.open(file).getexif()), 0)

    def test_forged_types_corrupt_files_and_svg_are_rejected(self):
        for file in (
            SimpleUploadedFile("photo.png", b"<script>fake</script>", content_type="image/png"),
            SimpleUploadedFile("photo.svg", b"<svg/>", content_type="image/svg+xml"),
            photo_file("photo.jpg"),
            SimpleUploadedFile("photo.png", photo_file().read()[:25], content_type="image/png"),
        ):
            self.assertEqual(self.upload(file).status_code, 400)
        self.assertEqual(ConversationPhoto.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)

    @override_settings(PHOTO_MAX_BYTES=100)
    def test_oversized_upload_is_rejected_before_processing(self):
        file = SimpleUploadedFile("photo.jpg", b"x" * 101, content_type="image/jpeg")
        with patch("conversations.photos.get_provider") as provider:
            self.assertEqual(self.upload(file).status_code, 413)
            provider.assert_not_called()
        self.assertEqual(ConversationPhoto.objects.count(), 0)

    @override_settings(PHOTO_MAX_PIXELS=100)
    def test_excessive_pixel_count_is_rejected(self):
        self.assertEqual(self.upload(photo_file(size=(20, 20))).status_code, 400)

    @override_settings(PHOTO_MAX_DIMENSION=20)
    def test_excessive_dimension_is_rejected(self):
        self.assertEqual(self.upload().status_code, 400)

    def test_animated_png_is_rejected(self):
        output = BytesIO()
        Image.new("RGB", (10, 10), "red").save(output, format="PNG", save_all=True,
                                                append_images=[Image.new("RGB", (10, 10), "blue")])
        file = SimpleUploadedFile("photo.png", output.getvalue(), content_type="image/png")
        self.assertEqual(self.upload(file).status_code, 400)

    def test_urls_and_extra_fields_are_not_accepted(self):
        for body in ({"url": "https://example.com/private.png"}, {"photo": photo_file(), "url": "https://example.com"}):
            self.assertEqual(self.client.post(self.url, body, format="multipart").status_code, 400)

    def test_missing_auth_rejects_upload_and_download(self):
        data = self.upload().json()
        self.client.credentials()
        self.assertEqual(self.upload().status_code, 401)
        self.assertEqual(self.client.get(data["content_url"]).status_code, 401)

    def test_other_conversation_access_is_rejected_before_decoding(self):
        other = InternetService.objects.get(service_identifier="DEMO-SERVICE-002")
        conversation = Conversation.objects.create(customer=other.customer, internet_service=other)
        with patch("conversations.photos.validate_photo") as validator:
            response = self.client.post(reverse("api:conversation-photos", args=[conversation.pk]), {"photo": photo_file()}, format="multipart")
            self.assertEqual(response.status_code, 404)
            validator.assert_not_called()

    def test_other_service_session_cannot_read_photo_or_analysis(self):
        data = self.upload().json()
        other = InternetService.objects.get(service_identifier="DEMO-SERVICE-002")
        _, token = issue_demo_session(operator=self.user, internet_service=other)
        self.client.credentials(HTTP_AUTHORIZATION=f"Demo {token}")
        for url in (data["content_url"], reverse("api:photo-detail", args=[data["id"]]), self.url):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_closed_conversation_disallows_upload(self):
        self.conversation.status = "CLOSED"
        self.conversation.save()
        self.assertEqual(self.upload().status_code, 400)

    def test_api_failure_keeps_photo_history_and_uncertainty(self):
        with patch("conversations.photos.get_provider") as factory:
            factory.return_value.analyze_photo.side_effect = ProviderError("timeout")
            with self.assertLogs("conversations.photos", level="WARNING"):
                response = self.upload()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "FAILED")
        self.assertTrue(data["analysis"]["uncertainties"])
        self.assertFalse(data["analysis"]["connectivity_confirmed"])
        self.assertEqual(Message.objects.count(), 2)
        self.assertTrue(photo_storage().exists(ConversationPhoto.objects.get().storage_key))

    def test_invalid_model_output_cannot_confirm_connectivity_or_request_unsafe_actions(self):
        for output in (
            {"observations": [], "uncertainties": [], "recommended_actions": ["CONTACT_SUPPORT"], "connectivity_confirmed": False},
            {"observations": [], "uncertainties": ["Unclear"], "recommended_actions": ["CLIMB_ROOF"], "connectivity_confirmed": True},
        ):
            with patch("conversations.photos.get_provider") as factory:
                factory.return_value.analyze_photo.return_value = output
                with self.assertLogs("conversations.photos", level="WARNING"):
                    self.assertEqual(self.upload().json()["status"], "FAILED")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_catalog_assets_and_chat_references_are_predefined(self):
        for language in ("es", "en"):
            for item in catalog(language):
                self.assertTrue((ASSET_ROOT / item["path"]).is_file())
                response = self.client.get(item["url"])
                self.assertEqual(response.status_code, 200)
                response.close()
        data = self.client.post(reverse("api:chat"), {"conversation_id": self.conversation.pk, "message": "Sin Internet"}, format="json").json()
        self.assertEqual([item["id"] for item in data["images"]], ["poe-es", "lights-es", "ethernet-es", "recheck-es"])
        self.assertEqual(Message.objects.last().metadata["image_ids"], [item["id"] for item in data["images"]])

    def test_catalog_unknown_id_and_unsupported_language(self):
        self.assertEqual(self.client.get(reverse("api:instruction-image", args=["unknown"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("api:instruction-catalog"), {"language": "xx"}).status_code, 400)

    def test_invalid_cursor_returns_validation_error(self):
        self.assertEqual(self.client.get(self.url, {"after": "not-a-uuid"}).status_code, 400)

    def test_original_storage_path_is_not_public(self):
        self.upload()
        photo = ConversationPhoto.objects.get()
        self.assertEqual(self.client.get(f"/private_media/{photo.storage_key}").status_code, 404)

    def test_english_demo_analysis_and_recommendations(self):
        self.conversation.language = "en"
        self.conversation.save()
        data = self.upload().json()
        self.assertIn("SIMULATED", data["analysis"]["observations"][0])
        self.assertIn("Contact technical support", data["recommendations"][1])

    def test_duplicate_file_fields_are_rejected(self):
        response = self.client.post(self.url, {"photo": [photo_file(), photo_file()]}, format="multipart")
        self.assertEqual(response.status_code, 400)

    @patch("conversations.photos.Message.objects.create")
    def test_database_failure_compensates_saved_file(self, mocked):
        mocked.side_effect = RuntimeError("simulated_database_failure")
        with self.assertLogs("django.request", level="ERROR"), self.assertRaises(RuntimeError):
            self.upload()
        self.assertEqual(list(Path(self.directory.name).rglob("*.jpg")), [])


class EnvironmentTests(SimpleTestCase):
    def test_local_env_loads_without_overwriting_process_values(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as directory, patch.dict(os.environ, {"DJANGO_ENV": "development", "AI_PROVIDER": "demo"}, clear=True):
            path = Path(directory)
            (path / ".env").write_text('AI_PROVIDER=openai\nOPENAI_MODEL="configured-local-model"\n', encoding="utf-8")
            load_development_env(path)
            self.assertEqual(os.environ["AI_PROVIDER"], "demo")
            self.assertEqual(os.environ["OPENAI_MODEL"], "configured-local-model")

    def test_production_does_not_load_dotenv(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as directory, patch.dict(os.environ, {"DJANGO_ENV": "production"}, clear=True):
            path = Path(directory)
            (path / ".env").write_text("AI_PROVIDER=openai\n", encoding="utf-8")
            load_development_env(path)
            self.assertNotIn("AI_PROVIDER", os.environ)

    def test_django_settings_invokes_development_loader(self):
        # Ejecutar settings en un proceso aislado no revela ni modifica el .env real.
        import subprocess
        import sys
        script = "from unittest.mock import patch; from pathlib import Path;\nwith patch('config.env_loading.load_development_env') as loader:\n import config.settings as config\n assert loader.call_count == 1\n assert loader.call_args.args == (config.BASE_DIR,)\n print('settings_loader_ok')"
        completed = subprocess.run([sys.executable, "-c", script], cwd=settings.BASE_DIR, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("settings_loader_ok", completed.stdout)


class VisionProviderTests(SimpleTestCase):
    def config(self):
        return SimpleNamespace(OPENAI_API_KEY=sentinel.api_key, OPENAI_VISION_MODEL="configured-vision-model", AI_TIMEOUT_SECONDS=15)

    def test_official_sdk_receives_only_image_and_minimal_context(self):
        analysis = VisualAnalysis(observations=["A cable is visible."], uncertainties=["Connection cannot be verified."], recommended_actions=["CONTACT_SUPPORT"], connectivity_confirmed=False)
        with patch("conversations.ai.settings", self.config()), patch("conversations.ai.OpenAI") as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=analysis)
            result = OpenAIProvider().analyze_photo(image=b"normalized-photo", mime_type="image/jpeg", language="en")
            call = client.responses.parse.call_args.kwargs
            content = call["input"][0]["content"]
            self.assertTrue(content[1]["image_url"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(content[1]["detail"], "low")
            self.assertNotIn("tools", call)
            self.assertFalse(call["store"])
            self.assertFalse(result.connectivity_confirmed)

    def test_vision_timeout_and_refusal_are_sanitized(self):
        with patch("conversations.ai.settings", self.config()), patch("conversations.ai.OpenAI") as sdk:
            client = sdk.return_value.__enter__.return_value
            client.responses.parse.side_effect = APITimeoutError(request=Mock())
            with self.assertRaises(ProviderError):
                OpenAIProvider().analyze_photo(image=b"photo", mime_type="image/jpeg", language="en")
            client.responses.parse.side_effect = None
            client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=None)
            with self.assertRaises(ProviderError):
                OpenAIProvider().analyze_photo(image=b"photo", mime_type="image/jpeg", language="en")
