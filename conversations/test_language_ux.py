from types import SimpleNamespace
from unittest.mock import patch, sentinel
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from . import test_web
from .ai import DemoAIProvider, OpenAIProvider, Interpretation, detect_language
from .instructions import relevant_images, ASSET_ROOT
from .models import Conversation, Message
from tickets.models import Ticket

@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV="development", AI_PROVIDER="demo")
class LanguageUXTests(TestCase):
    setUp = test_web.DemoWebTests.setUp

    def select(self, language):
        self.client.post("/demo/session/", {"service_id":self.service.pk}, HTTP_X_CSRFTOKEN=self.csrf)
        return self.client.post("/demo/language/", {"language":language}, HTTP_X_CSRFTOKEN=self.csrf)

    def send(self, message, conversation=None, language=None):
        body={"message":message, "conversation_id" if conversation else "service_id":conversation or self.service.pk}
        if language: body["language"]=language
        return self.client.post("/api/chat/",body,content_type="application/json",HTTP_X_CSRFTOKEN=self.csrf)

    def test_initial_confirmation_required_on_server(self):
        self.client.post("/demo/session/", {"service_id":self.service.pk}, HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(self.send("Hello").status_code,400)
        self.assertEqual(Conversation.objects.count(),0)
        self.assertEqual(self.client.post("/demo/language/",{"language":"en"}).status_code,403)
        self.assertEqual(self.client.post("/demo/language/",{"language":"xx"},HTTP_X_CSRFTOKEN=self.csrf).status_code,400)

    def test_initial_languages_and_ambiguous_acknowledgment(self):
        for language in ("en","es"):
            self.select(language)
            result=self.send("OK").json()
            self.assertEqual(result["language"],language)
            self.assertEqual(Conversation.objects.get(pk=result["conversation_id"]).language,language)

    def test_adaptive_switching_continuity_and_manual_override(self):
        self.select("en")
        first=self.send("My internet is not working.").json()
        conversation=first["conversation_id"]
        self.assertEqual(first["language"],"en")
        second=self.send("Ya revisé los cables, pero todavía no funciona.",conversation).json()
        self.assertEqual(second["language"],"es")
        self.assertEqual(second["ticket"]["status"],"OPEN")
        self.assertEqual(second["images"],[])
        self.assertIn("Gracias",second["message"])
        self.assertEqual(self.send("OK PoE Ethernet router",conversation).json()["language"],"es")
        self.assertEqual(self.send("I checked the cables",conversation).json()["language"],"en")
        self.assertEqual(self.send("OK",conversation,language="es").json()["language"],"es")
        self.assertEqual(Ticket.objects.count(),1)
        ticket=Ticket.objects.get()
        self.assertEqual(ticket.title,"The CPE is not responding in the simulation.")
        self.assertEqual(Message.objects.filter(conversation_id=conversation).count(),10)
        state=self.client.get("/demo/state/").json()
        self.assertEqual(state["language"],"es")
        self.assertTrue(state["language_confirmed"])
        self.assertTrue(timezone.is_aware(ticket.created_at))

    def test_guides_follow_active_language_and_steps(self):
        self.select("en")
        first=self.send("No Internet").json()
        second=self.send("No tengo Internet",first["conversation_id"]).json()
        for language,result in (("en",first),("es",second)):
            self.assertEqual([entry["step_number"] for entry in result["images"]],[1,2,3,4])
            self.assertTrue(all(entry["language"]==language for entry in result["images"]))
            self.assertTrue(all(entry["source"]=="supplied_ai_generated_demo" and not entry["production_approved"] for entry in result["images"][:3]))
            self.assertEqual(result["images"][3]["source"], "original_demo")
            self.assertEqual(result["images"][3]["license"], "CC0-1.0")

    def test_interface_english_and_display_timezone_configurable(self):
        response=self.client.get("/demo/")
        for text in ['lang="en-US"','Welcome to ISP Support','Choose your preferred language','Continue','Technical panel','Photo preview','id="image-zoom"']:
            self.assertContains(response,text)
        self.assertNotContains(response,"Centro de atención")
        with override_settings(TIME_ZONE="America/New_York"):
            self.assertEqual(self.client.get("/demo/state/").json()["time_zone"],"America/New_York")

    def test_missing_asset_returns_safe_404(self):
        self.select("en")
        with patch("conversations.media_api.ASSET_ROOT",ASSET_ROOT / "missing"):
            self.assertEqual(self.client.get("/api/instructions/poe-en/").status_code,404)

    def test_historical_generated_summary_translation_preserves_customer_text(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        self.select("es")
        conversation=self.send("No tengo Internet").json()["conversation_id"]
        self.send("Ya revisé los cables",conversation)
        ticket=Ticket.objects.get()
        old_title="La CPE no responde en la simulación."
        Ticket.objects.filter(pk=ticket.pk).update(title=old_title,description='{"summary":"'+old_title+'","note":"Texto original del cliente"}')
        original=list(Message.objects.values_list("content",flat=True))
        migration=import_module("diagnostics.migrations.0004_translate_technical_summaries")
        migration.forwards(apps,SimpleNamespace(connection=connection))
        ticket.refresh_from_db()
        self.assertEqual(ticket.title,"The CPE is not responding in the simulation.")
        self.assertIn("Texto original del cliente",ticket.description)
        self.assertEqual(list(Message.objects.values_list("content",flat=True)),original)

class ProviderLanguageTests(SimpleTestCase):
    def test_both_providers_share_conservative_language_policy(self):
        cases=[("Ya revisé los cables, pero todavía no funciona.","en","es"),
               ("I checked the cables but it is still not working.","es","en"),
               ("OK", "es","es"),("PoE Ethernet router LED", "en","en")]
        for message,previous,expected in cases:
            self.assertEqual(DemoAIProvider().interpret(message=message,history=[],language=previous).language,expected)
            with patch("conversations.ai.settings",SimpleNamespace(OPENAI_API_KEY=sentinel.key,OPENAI_MODEL="configured-model",AI_TIMEOUT_SECONDS=15)),patch("conversations.ai.OpenAI") as factory:
                factory.return_value.__enter__.return_value.responses.parse.return_value=SimpleNamespace(status="completed",output_parsed=Interpretation(intent="OTHER",language="en" if expected=="es" else "es"))
                result=OpenAIProvider().interpret(message=message,history=[],language=previous)
                self.assertEqual(result.language,expected)
