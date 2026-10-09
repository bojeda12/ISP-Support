"""Integración web con cookies reales, CSRF y aislamiento de servicios."""
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from customers.models import InternetService
from .models import Conversation, DemoChatSession, Message


@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV="development", AI_PROVIDER="demo")
class DemoWebTests(TestCase):
    def setUp(self):
        call_command("seed_demo", stdout=StringIO())
        self.service = InternetService.objects.get(service_identifier="DEMO-SERVICE-001")
        self.operator = get_user_model().objects.create_user(username="web-operator", is_staff=True)
        self.operator.user_permissions.add(Permission.objects.get(codename="use_demo_chat"))
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.operator)
        self.client.get("/demo/")
        self.csrf = self.client.cookies["csrftoken"].value

    def select(self, service=None):
        response = self.client.post("/demo/session/", {"service_id": (service or self.service).pk}, HTTP_X_CSRFTOKEN=self.csrf)
        self.client.post("/demo/language/", {"language": "es"}, HTTP_X_CSRFTOKEN=self.csrf)
        return response

    def chat(self, text, conversation=None, language="es", csrf=True):
        data = {"message": text, "language": language,
                "conversation_id" if conversation else "service_id": conversation or self.service.pk}
        return self.client.post("/api/chat/", data, content_type="application/json",
                                **({"HTTP_X_CSRFTOKEN": self.csrf} if csrf else {}))

    def test_page_requires_operator_and_development(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/demo/"), "/admin/login/?next=/demo/", fetch_redirect_response=False)
        self.client.force_login(get_user_model().objects.create_user(username="unauthorized", is_staff=True))
        self.assertEqual(self.client.get("/demo/").status_code, 403)
        with override_settings(DEBUG=False):
            self.assertEqual(self.client.get("/demo/").status_code, 404)

    def test_page_uses_local_assets_and_content_security_policy(self):
        response = self.client.get("/demo/")
        self.assertContains(response, "bootstrap.min.css")
        self.assertContains(response, 'name="viewport"')
        self.assertContains(response, "demo-core.js")
        self.assertNotContains(response, "cdn.jsdelivr.net")
        self.assertNotContains(response, "Authorization")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_selection_csrf_and_api_csrf_are_required(self):
        self.assertEqual(self.client.post("/demo/session/", {"service_id": self.service.pk}).status_code, 403)
        self.assertEqual(self.select().status_code, 200)
        self.assertEqual(self.chat("Hola", csrf=False).status_code, 403)
        self.assertEqual(self.chat("Hola").status_code, 200)

    def test_cookie_start_continue_language_history_and_reload(self):
        state = self.select().json()
        self.assertNotIn("token", state)
        first = self.chat("Hola").json()
        second = self.chat("Hello", first["conversation_id"], language="en").json()
        self.assertEqual(second["language"], "en")
        state = self.client.get("/demo/state/").json()
        self.assertEqual(state["conversation_id"], first["conversation_id"])
        history = self.client.get(f'/api/conversations/{first["conversation_id"]}/messages/').json()
        self.assertEqual(len(history["messages"]), 4)
        self.assertEqual(history["language"], "en")
        self.assertEqual(Conversation.objects.count(), 1)

    def test_followup_escalation_preserves_rules_without_repeated_instructions(self):
        for language, start, confirm, expected in (
            ("es", "No tengo Internet", "Ya revisé el PoE y los cables", "Gracias"),
            ("en", "No Internet", "I checked the PoE and cables", "Thank"),
        ):
            self.select()
            first = self.chat(start, language=language).json()
            self.assertTrue(first["images"])
            image = self.client.get(first["images"][0]["url"])
            self.assertEqual(image.status_code, 200)
            second = self.chat(confirm, first["conversation_id"], language=language).json()
            self.assertEqual(second["diagnostic"]["result_code"], "CPE_UNREACHABLE")
            self.assertEqual(second["ticket"]["status"], "OPEN")
            self.assertIn(expected, second["message"])
            self.assertEqual(second["images"], [])
            history = self.client.get(f'/api/conversations/{first["conversation_id"]}/messages/').json()
            self.assertEqual(history["messages"][-1]["ticket"]["number"], second["ticket"]["number"])

    def test_cross_service_history_denied_and_session_revoked(self):
        self.select()
        conversation = self.chat("Hola").json()["conversation_id"]
        previous = self.client.session["demo_session_id"]
        self.select(InternetService.objects.get(service_identifier="DEMO-SERVICE-002"))
        self.assertTrue(DemoChatSession.objects.get(pk=previous).revoked)
        self.assertEqual(self.client.get(f"/api/conversations/{conversation}/messages/").status_code, 404)
        self.assertIsNone(self.client.get("/demo/state/").json()["conversation_id"])
        self.client.logout()
        self.assertEqual(self.client.get(f"/api/conversations/{conversation}/messages/").status_code, 401)

    def test_non_demo_selection_rejected(self):
        self.assertEqual(self.client.post("/demo/session/", {"service_id": 999999}, HTTP_X_CSRFTOKEN=self.csrf).status_code, 400)

    def test_technician_admin_exposes_conversation_diagnostics_and_events(self):
        self.select()
        first = self.chat("No tengo Internet").json()
        second = self.chat("Ya revisé el PoE", first["conversation_id"]).json()
        self.operator.is_superuser = True
        self.operator.save()
        response = self.client.get(f'/admin/tickets/ticket/{second["ticket"]["id"]}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'/admin/conversations/conversation/{first["conversation_id"]}/change/')
        self.assertContains(response, '/admin/diagnostics/diagnosticrun/')
        self.assertContains(response, 'CPE_UNREACHABLE')
        self.assertGreater(response.context["inline_admin_formsets"][0].formset.queryset.count(), 0)

    def test_history_pagination_and_untrusted_text(self):
        self.select()
        conversation = self.chat("<img src=x onerror=alert(1)>").json()["conversation_id"]
        Message.objects.bulk_create([Message(conversation_id=conversation, sender="customer", content=str(n)) for n in range(55)])
        path = f"/api/conversations/{conversation}/messages/"
        latest = self.client.get(path).json()
        self.assertEqual(len(latest["messages"]), 50)
        older = self.client.get(path, {"before": latest["next_before"]}).json()
        self.assertEqual(len(older["messages"]), 7)
        self.assertIn("<img", older["messages"][0]["content"])
        self.assertLess(older["messages"][-1]["id"], latest["messages"][0]["id"])
        self.assertEqual(self.client.get(path, {"before": "invalid"}).status_code, 400)

    def test_cookie_photo_upload_history_and_private_retrieval(self):
        self.select()
        conversation = self.chat("Hola").json()["conversation_id"]
        buffer = BytesIO()
        Image.new("RGB", (20, 20), "blue").save(buffer, format="PNG")
        with TemporaryDirectory(dir=settings.BASE_DIR) as directory, override_settings(PRIVATE_MEDIA_ROOT=directory):
            response = self.client.post(f"/api/conversations/{conversation}/photos/",
                {"photo": SimpleUploadedFile("demo.png", buffer.getvalue(), content_type="image/png")}, HTTP_X_CSRFTOKEN=self.csrf)
            self.assertEqual(response.status_code, 201, response.content)
            photo = response.json()
            self.assertTrue(photo["simulated"])
            self.assertTrue(photo["analysis"]["uncertainties"])
            content = self.client.get(photo["content_url"])
            self.assertEqual(content.status_code, 200)
            content.close()  # FileResponse debe soltar el archivo antes de limpiar en Windows.
            history = self.client.get(f"/api/conversations/{conversation}/messages/").json()
            self.assertEqual(history["messages"][-1]["photo"]["id"], photo["id"])
            self.select(InternetService.objects.get(service_identifier="DEMO-SERVICE-002"))
            self.assertEqual(self.client.get(photo["content_url"]).status_code, 404)
