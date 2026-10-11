"""Regresión real: cuota de servicio agotada, sesiones y mensajes persistentes."""
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase,override_settings
from django.utils import timezone
from . import test_confirmed_recheck
from .models import Conversation,Message,DemoChatSession
from diagnostics.models import DiagnosticRun
from tickets.models import Ticket

@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo')
class RecoveryRegressionTests(TestCase):
    setUp=test_confirmed_recheck.ConfirmedRecheckTests.setUp
    select=test_confirmed_recheck.ConfirmedRecheckTests.select
    send=test_confirmed_recheck.ConfirmedRecheckTests.send
    follow=test_confirmed_recheck.ConfirmedRecheckTests.follow
    post=test_confirmed_recheck.ConfirmedRecheckTests.post
    private_storage=test_confirmed_recheck.ConfirmedRecheckTests.private_storage

    def assert_saved(self,conversation,count):
        state=self.client.get('/demo/state/').json()
        self.assertEqual(state['conversation_id'],conversation)
        self.assertEqual(self.client.get('/demo/').status_code,200)
        history=self.client.get(f'/api/conversations/{conversation}/messages/')
        self.assertEqual(history.status_code,200)
        self.assertEqual(len(history.json()['messages']),count)
        return history.json()['messages']

    def test_actual_six_runs_then_new_conversation_reports_limit_not_broken_simulator(self):
        self.select('en')
        first=self.post("I don't have Internet.",photo=False).json()
        run=DiagnosticRun.objects.get(pk=first['diagnostic']['id'])
        for _ in range(4):
            run.pk=None; run.save(force_insert=True)
        limited=self.post("I don't have Internet.",photo=False).json()
        self.assertEqual(limited['requires_action'],'WAIT_DIAGNOSTIC_LIMIT')
        self.assertEqual(limited['debug']['chat']['tool_result']['reason'],'frequency_limit')
        self.assertGreater(limited['debug']['chat']['tool_result']['retry_after_seconds'],0)
        self.assertIn('limit',limited['message'])
        self.assertNotIn('could not be completed',limited['message'])
        self.assertIsNone(limited['diagnostic'])
        self.assertEqual(DiagnosticRun.objects.filter(internet_service=self.service).count(),6)
        self.assert_saved(limited['conversation_id'],2)
        DiagnosticRun.objects.filter(internet_service=self.service).update(created_at=timezone.now()-timedelta(hours=2))
        retry=self.post("I don't have Internet.",photo=False,conversation_id=limited['conversation_id'])
        self.assertEqual(retry.status_code,200,retry.content)
        self.assertEqual(retry.json()['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertTrue(retry.json()['images'])
        self.assertEqual(retry.json()['conversation_id'],limited['conversation_id'])
        self.assert_saved(limited['conversation_id'],4)

    def test_initial_exception_refresh_retry_then_ticket_preserves_history(self):
        self.select('en'); key=uuid.uuid4()
        with patch('conversations.services.run_diagnostic',side_effect=ValidationError('Invalid simulator state')),self.assertLogs('conversations.services',level='ERROR') as logs:
            failed=self.post("I don't have Internet.",photo=False,request_id=key)
        self.assertEqual(failed.status_code,200,failed.content)
        data=failed.json(); self.assertIn('ValidationError', '\n'.join(logs.output))
        self.assertIn('Invalid simulator state','\n'.join(logs.output))
        self.assertEqual(data['requires_action'],'CONTACT_DEMO_OPERATOR')
        self.assert_saved(data['conversation_id'],2)
        self.assertEqual(self.post("I don't have Internet.",photo=False,request_id=key).json(),data)
        recovered=self.post("I don't have Internet.",photo=False,conversation_id=data['conversation_id']).json()
        self.assertEqual(recovered['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertTrue(recovered['images'])
        text="I checked the cables, router and PoE power. Everything is connected but Internet still doesn't work."
        ticket=self.post(text,photo=False,conversation_id=data['conversation_id']).json()
        self.assertEqual(ticket['ticket']['status'],'OPEN')
        self.assertIn(ticket['ticket']['number'],ticket['message'])
        rows=self.assert_saved(data['conversation_id'],6)
        self.assertEqual(rows[-1]['ticket']['number'],ticket['ticket']['number'])
        repeat=self.post(text,photo=False,conversation_id=data['conversation_id']).json()
        self.assertEqual(repeat['ticket']['number'],ticket['ticket']['number'])
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(Conversation.objects.count(),1)
        self.assertEqual(DiagnosticRun.objects.filter(conversation_id=data['conversation_id']).count(),2)

    def test_reconnect_same_service_preserves_conversation_and_ticket(self):
        self.select('en')
        first=self.post("I don't have Internet.",photo=False).json()
        old_id=self.client.session['demo_session_id']
        DemoChatSession.objects.filter(pk=old_id).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIsNone(self.client.get('/demo/state/').json()['service'])
        response=self.client.post('/demo/session/',{'service_id':self.service.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['conversation_id'],first['conversation_id'])
        self.assert_saved(first['conversation_id'],2)
        self.assertTrue(DemoChatSession.objects.get(pk=old_id).revoked)

    def test_initial_success_and_csrf_preserve_existing_authorization(self):
        self.select('en')
        self.assertEqual(self.post("I don't have Internet.",photo=False,csrf=False).status_code,403)
        first=self.post("I don't have Internet.",photo=False).json()
        self.assertEqual(first['diagnostic']['result_code'],'CPE_UNREACHABLE')
        self.assertTrue(first['images'])
        self.assert_saved(first['conversation_id'],2)
        self.client.logout()
        self.assertIn(self.client.get(f"/api/conversations/{first['conversation_id']}/messages/").status_code,[401,403])

    def test_login_again_resumes_only_own_latest_turn_for_service(self):
        self.select('en')
        first=self.post("I don't have Internet.",photo=False).json()
        self.client.logout(); self.client.force_login(self.operator)
        self.client.get('/demo/'); self.csrf=self.client.cookies['csrftoken'].value
        response=self.client.post('/demo/session/',{'service_id':self.service.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(response.json()['conversation_id'],first['conversation_id'])
        self.assert_saved(first['conversation_id'],2)
        self.client.logout()
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        other=get_user_model().objects.create_user(username='other-recovery-operator',is_staff=True)
        other.user_permissions.add(Permission.objects.get(codename='use_demo_chat'))
        self.client.force_login(other);self.client.get('/demo/');self.csrf=self.client.cookies['csrftoken'].value
        response=self.client.post('/demo/session/',{'service_id':self.service.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertIsNone(response.json()['conversation_id'])
