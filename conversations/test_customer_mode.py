"""Vista cliente local sin herramientas internas y continuidad autorizada."""
from datetime import timedelta
from django.test import TestCase,override_settings
from django.utils import timezone
from . import test_recovery_regression
from .models import Conversation,DemoChatSession
from customers.models import InternetService

@override_settings(ENABLE_DEMO_CHAT=True,DEBUG=True,DJANGO_ENV='development',AI_PROVIDER='demo')
class CustomerModeTests(TestCase):
    setUp=test_recovery_regression.RecoveryRegressionTests.setUp
    select=test_recovery_regression.RecoveryRegressionTests.select
    post=test_recovery_regression.RecoveryRegressionTests.post
    private_storage=test_recovery_regression.RecoveryRegressionTests.private_storage

    def test_customer_markup_excludes_operator_tools_but_operator_keeps_them(self):
        customer=self.client.get('/demo/customer/')
        self.assertEqual(customer.status_code,200)
        for marker in ['id="service-select"','id="previous-chats"','id="resume-chat"','id="new-chat"','id="session-summary"','Previous chats','Resume chat','New chat','/admin/','DEMO-CUSTOMER-001']:
            self.assertNotContains(customer,marker)
        for marker in ['id="messages"','id="photo-input"','id="message-input"','id="ticket-summary"','id="reconnect-chat"']:
            self.assertContains(customer,marker)
        operator=self.client.get('/demo/')
        self.assertNotContains(operator,'id="previous-chats"')
        self.assertNotContains(operator,'Previous chats')
        self.assertNotContains(operator,'Customer preview')
        self.assertContains(operator,'id="new-chat"')
        self.assertNotContains(operator,'id="resume-chat"')
        self.assertContains(operator,'id="service-select"')
        self.assertContains(operator,'id="connect-button"')
        self.assertNotIn('runtime',self.client.get('/demo/customer/state/').json())

    def test_operator_management_is_not_public(self):
        from django.contrib.auth import get_user_model
        self.client.logout()
        for path in ['/demo/', '/demo/conversations/', '/demo/customer/state/']:
            self.assertEqual(self.client.get(path).status_code,302)
        ordinary=get_user_model().objects.create_user(username='preview-unprivileged')
        self.client.force_login(ordinary)
        for path in ['/demo/', '/demo/customer/', '/demo/conversations/']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/demo/conversation/').status_code,403)
        ordinary.is_staff=True
        ordinary.save(update_fields=['is_staff'])
        self.assertEqual(self.client.get('/demo/conversations/').status_code,403)

    def test_multiple_turns_photo_ticket_and_refresh_same_conversation(self):
        self.private_storage();self.select('es')
        first=self.post('No tengo internet.',photo=False).json();cid=first['conversation_id']
        self.assertTrue(first['images'])
        second=self.post('Revisé los cables, el router y la alimentación PoE. Todo está conectado pero sigo sin Internet.',photo=True,conversation_id=cid).json()
        self.assertEqual(second['conversation_id'],cid)
        self.assertIsNotNone(second['ticket'])
        self.client.get('/demo/')
        state=self.client.get('/demo/state/').json()
        self.assertEqual(state['conversation_id'],cid)
        history=self.client.get(f'/api/conversations/{cid}/messages/').json()['messages']
        self.assertEqual(len(history),4)
        self.assertTrue(history[1]['images'])
        self.assertIsNotNone(history[2]['photo'])
        self.assertEqual(history[3]['ticket']['number'],second['ticket']['number'])

    def test_reconnect_ignores_browser_service_and_preserves_authorized_case(self):
        self.select('en');first=self.post('No Internet',photo=False).json();cid=first['conversation_id']
        DemoChatSession.objects.filter(pk=self.client.session['demo_session_id']).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIsNone(self.client.get('/demo/customer/state/').json()['service'])
        other=InternetService.objects.get(service_identifier='DEMO-SERVICE-002')
        self.assertEqual(self.client.post('/demo/customer/reconnect/',{'service_id':other.pk}).status_code,403)
        response=self.client.post('/demo/customer/reconnect/',{'service_id':other.pk,'conversation_id':999},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['service']['id'],self.service.pk)
        self.assertEqual(response.json()['conversation_id'],cid)
        self.assertEqual(Conversation.objects.get(pk=cid).messages.count(),2)
        self.client.logout()
        redirect=self.client.get('/demo/customer/')
        self.assertIn('next=/demo/customer/',redirect.url)

    def test_unbound_customer_cannot_choose_identity_or_reconnect(self):
        response=self.client.post('/demo/customer/reconnect/',{'service_id':self.service.pk},HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(response.status_code,403)
        with override_settings(ENABLE_DEMO_CHAT=False):
            self.assertEqual(self.client.get('/demo/customer/').status_code,404)
