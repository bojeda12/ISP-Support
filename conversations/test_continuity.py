"""Aislamiento, selecciÃ³n explÃ­cita y escenarios reales de la demo."""
import json,uuid
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from customers.models import InternetService
from diagnostics.services import set_demo_scenario
from tickets.models import Ticket
from .models import Conversation, Message, DemoChatSession
from .context import conversation_context
from . import test_recovery_regression

@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo')
class ContinuityTests(TestCase):
    setUp=test_recovery_regression.RecoveryRegressionTests.setUp
    select=test_recovery_regression.RecoveryRegressionTests.select
    post=test_recovery_regression.RecoveryRegressionTests.post
    private_storage=test_recovery_regression.RecoveryRegressionTests.private_storage

    def choose(self, **body):
        return self.client.post('/demo/conversation/',body,HTTP_X_CSRFTOKEN=self.csrf)

    def test_new_resume_photos_pagination_refresh_and_service_switch(self):
        self.private_storage();self.select('es')
        first=self.post('No tengo internet.',photo=True).json();old=first['conversation_id']
        c=Conversation.objects.get(pk=old)
        Message.objects.bulk_create([Message(conversation=c,sender='customer',content='Saved message') for _ in range(55)])
        self.assertEqual(self.choose(action='new').status_code,200)
        self.assertIsNone(self.client.get('/demo/state/').json()['conversation_id'])
        fresh=self.post('No tengo internet.',photo=False).json()
        self.assertNotEqual(fresh['conversation_id'],old)
        state=conversation_context(Conversation.objects.get(pk=fresh['conversation_id']))
        self.assertEqual(state['completed_checks'],[])
        self.assertIsNone(fresh['ticket'])
        self.assertTrue(fresh['images'])
        ids=[x['id'] for x in self.client.get('/demo/conversations/').json()['conversations']]
        self.assertIn(old,ids)
        self.assertEqual(self.choose(conversation_id=old).json()['conversation_id'],old)
        page=self.client.get(f'/api/conversations/{old}/messages/').json()
        self.assertEqual(len(page['messages']),50)
        older=self.client.get(f"/api/conversations/{old}/messages/?before={page['next_before']}").json()
        self.assertIsNotNone(older['messages'][0]['photo'])
        self.client.get('/demo/')
        self.assertEqual(self.client.get('/demo/state/').json()['conversation_id'],old)
        self.assertEqual(c.photos.count(),1)
        second=InternetService.objects.get(service_identifier='DEMO-SERVICE-002')
        self.client.post('/demo/session/',{'service_id':second.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(self.choose(conversation_id=old).status_code,404)
        self.assertEqual(self.client.get(f'/api/conversations/{old}/messages/').status_code,404)
        self.select('es')
        self.assertIn(old,[x['id'] for x in self.client.get('/demo/conversations/').json()['conversations']])

    def test_weak_signal_is_valid_new_ticket_and_no_poe_guide(self):
        self.service=InternetService.objects.get(service_identifier='DEMO-SERVICE-002');self.select('es')
        first=self.post('No tengo internet.',photo=False).json()
        self.assertEqual(first['diagnostic']['result_code'],'SIGNAL_DEGRADED')
        self.assertEqual(first['diagnostic']['metrics']['cpe_online'],True)
        self.assertEqual(first['operation_outcome']['diagnostic']['execution'],'new')
        self.assertEqual(first['operation_outcome']['ticket']['action'],'created')
        self.assertEqual(first['images'],[])
        self.assertIn('continue',[x['id'] for x in first['quick_replies']])
        c=Conversation.objects.get(pk=first['conversation_id'])
        self.assertEqual(conversation_context(c)['completed_checks'],[])
        repeated=self.post('No tengo internet.',photo=False,conversation_id=c.pk).json()
        self.assertEqual(repeated['ticket']['number'],first['ticket']['number'])
        self.assertEqual(Ticket.objects.filter(conversation=c).count(),1)
        self.assertEqual(c.diagnostic_runs.count(),1)
        self.choose(action='new')
        second=self.post('No tengo internet.',photo=False).json()
        self.assertNotEqual(second['conversation_id'],c.pk)
        self.assertEqual(conversation_context(Conversation.objects.get(pk=second['conversation_id']))['completed_checks'],[])
        self.assertEqual(c.messages.count(),4)
        choice=second['quick_replies'][0]
        continued=self.client.post('/api/chat/turn/',{'request_id':str(uuid.uuid4()),'conversation_id':second['conversation_id'],'quick_reply':json.dumps({'id':choice['id'],'question_message_id':choice['question_message_id']})},HTTP_X_CSRFTOKEN=self.csrf).json()
        self.assertIn('¿No puedes navegar',continued['message'])
        self.assertEqual(continued['ticket']['number'],second['ticket']['number'])
        self.assertIn('slow',[x['id'] for x in continued['quick_replies']])


    def test_reconnect_operator_isolation_closed_readonly_and_csrf(self):
        self.select('en');first=self.post('No Internet',photo=False).json();cid=first['conversation_id']
        self.assertEqual(self.client.post('/demo/conversation/',{'action':'new'}).status_code,403)
        DemoChatSession.objects.filter(pk=self.client.session['demo_session_id']).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/demo/conversations/').status_code,403)
        self.select('en');self.assertEqual(self.client.get('/demo/state/').json()['conversation_id'],cid)
        Conversation.objects.filter(pk=cid).update(status='CLOSED')
        self.assertEqual(self.choose(conversation_id=cid).json()['conversation_status'],'CLOSED')
        DemoChatSession.objects.filter(pk=self.client.session['demo_session_id']).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.select('en')
        self.assertEqual(self.client.get('/demo/state/').json()['conversation_id'],cid)
        self.assertEqual(self.client.get(f'/api/conversations/{cid}/messages/').status_code,200)
        self.assertEqual(self.post('Hello',photo=False,conversation_id=cid).status_code,400)
        other=get_user_model().objects.create_user(username='another-operator',is_staff=True)
        other.user_permissions.add(Permission.objects.get(codename='use_demo_chat'))
        self.client.force_login(other);self.select('en')
        self.assertEqual(self.client.get('/demo/conversations/').json()['conversations'],[])
        self.assertEqual(self.choose(conversation_id=cid).status_code,404)

    def test_healthy_and_suspended_do_not_fake_cpe_failure(self):
        self.select('en');set_demo_scenario(internet_service=self.service,scenario='HEALTHY')
        healthy=self.post('No Internet',photo=False).json()
        self.assertEqual(healthy['diagnostic']['result_code'],'NO_FAULT_DETECTED')
        self.assertIsNone(healthy['ticket'])
        self.service=InternetService.objects.get(service_identifier='DEMO-SERVICE-003');self.select('es')
        suspended=self.post('No tengo internet.',photo=False).json()
        self.assertIsNone(suspended['diagnostic'])
        self.assertIsNone(suspended['ticket'])
        self.assertIn('suspend',suspended['message'].lower())
        self.assertEqual(suspended['images'],[])
