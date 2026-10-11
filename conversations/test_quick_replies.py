"""Opciones opcionales: mismo flujo, herramientas reales simuladas y permisos."""
import json
import uuid
from unittest.mock import patch
from django.test import TestCase, override_settings
from . import test_confirmed_recheck
from .models import Conversation, Message
from tickets.models import Ticket

@override_settings(ENABLE_DEMO_CHAT=True, DEBUG=True, DJANGO_ENV='development', AI_PROVIDER='demo', CHAT_ALLOW_INCONCLUSIVE_REVIEW=True)
class QuickReplyTests(TestCase):
    setUp = test_confirmed_recheck.ConfirmedRecheckTests.setUp
    select = test_confirmed_recheck.ConfirmedRecheckTests.select
    private_storage = test_confirmed_recheck.ConfirmedRecheckTests.private_storage

    def choose(self, code, conversation=None, reference=None, key=None, photo=None, csrf=True):
        if not self.client.session.get('demo_session_id'): self.select('en')
        data={'request_id':str(key or uuid.uuid4()), 'quick_reply':json.dumps({'id':code,'question_message_id':reference}),
              'conversation_id' if conversation else 'service_id':conversation or self.service.pk}
        if photo: data['photo']=photo
        return self.client.post('/api/chat/turn/',data,**({'HTTP_X_CSRFTOKEN':self.csrf} if csrf else {}))

    def begin(self):
        result=self.choose('no_internet')
        self.assertEqual(result.status_code,200,result.content)
        data=result.json()
        self.conversation=Conversation.objects.get(pk=data['conversation_id'])
        return data

    def test_three_turn_flow_executes_recheck_and_one_ticket(self):
        first=self.begin()
        self.assertIn('checked',[item['id'] for item in first['quick_replies']])
        reference=first['quick_replies'][0]['question_message_id']
        before=self.conversation.diagnostic_runs.count()
        key=uuid.uuid4()
        from .adaptive import authorized_recheck
        from tickets.services import create_ticket
        with patch('conversations.services.authorized_recheck',wraps=authorized_recheck) as recheck, patch('diagnostics.services.create_ticket',wraps=create_ticket) as create:
            second=self.choose('checked',self.conversation.pk,reference,key)
        self.assertEqual(second.status_code,200,second.content)
        self.assertEqual(recheck.call_count,1)
        self.assertEqual(create.call_count,1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),before+1)
        data=second.json()
        self.assertEqual(data['ticket']['status'],'OPEN')
        self.assertEqual(data['quick_replies'],[])
        self.assertEqual(data['images'],[])
        self.assertEqual(self.choose('checked',self.conversation.pk,reference,key).json(),data)
        from .test_combined_turns import CombinedTurnTests
        third=CombinedTurnTests.post(self,"I still don't have Internet.",photo=False,conversation_id=self.conversation.pk)
        self.assertEqual(third.status_code,200,third.content)
        self.assertEqual(third.json()['ticket']['number'],data['ticket']['number'])
        self.assertEqual(Ticket.objects.count(),1)
        self.assertEqual(self.conversation.diagnostic_runs.count(),before+1)
        customer=self.conversation.messages.filter(sender='customer',metadata__quick_reply__id='checked').get()
        self.assertEqual(customer.metadata['quick_reply']['question_message_id'],reference)
        self.assertIn('power',customer.content)
        self.assertIn('cables',customer.content)

    def test_invalid_stale_and_cross_question_replies(self):
        first=self.begin(); reference=first['quick_replies'][0]['question_message_id']
        count=Message.objects.count()
        for code,ref in [('checked',None),('checked',reference+999),('forged',reference)]:
            self.assertEqual(self.choose(code,self.conversation.pk,ref).status_code,400)
        self.assertEqual(Message.objects.count(),count)
        self.assertEqual(self.choose('help',self.conversation.pk,reference).status_code,200)
        self.assertEqual(self.choose('checked',self.conversation.pk,reference).status_code,400)

    def test_csrf_and_anonymous_not_bypassed(self):
        self.select('en')
        self.assertEqual(self.choose('human',csrf=False).status_code,403)
        self.client.logout()
        self.assertIn(self.choose('human').status_code,[401,403])
        self.assertEqual(Ticket.objects.count(),0)

    def test_photo_and_choice_same_turn(self):
        self.private_storage(); self.begin()
        from .test_multimodal import photo_file
        ref=self.conversation.messages.filter(sender='assistant').latest('pk').pk
        result=self.choose('checked',self.conversation.pk,ref,photo=photo_file())
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(self.conversation.photos.count(),1)
        self.assertEqual(Ticket.objects.count(),1)

    def test_issue_categories_and_human_request(self):
        from .ai import DemoAIProvider
        from .quick_replies import offers
        choices={item['id']:item for item in offers()}
        for code,category in [('no_power','NO_POWER'),('drops','INTERMITTENT_CONNECTION')]:
            result=DemoAIProvider().interpret(message=choices[code]['message'],history=[],language='en')
            self.assertEqual(result.issue_category,category)
        result=self.choose('human')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['intent'],'REQUEST_TECHNICIAN')
        self.assertEqual(Ticket.objects.count(),1)

    def test_spanish_choices_and_history(self):
        self.select('es')
        result=self.choose('no_internet')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['language'],'es')
        conversation=result.json()['conversation_id']
        history=self.client.get(f'/api/conversations/{conversation}/messages/').json()['messages']
        self.assertEqual(history[-1]['quick_replies'][0]['labels']['es'],'Sí, lo revisé')

    def test_adapter_receives_bound_customer_response(self):
        first=self.begin(); ref=first['quick_replies'][0]['question_message_id']
        from .ai import DemoAIProvider
        provider=DemoAIProvider()
        with patch.object(provider,'interpret',wraps=provider.interpret) as interpret, patch('conversations.services.get_provider',return_value=provider):
            result=self.choose('unsure',self.conversation.pk,ref)
        self.assertEqual(result.status_code,200,result.content)
        context=interpret.call_args.kwargs['history'][0]['context']
        self.assertEqual(context['customer_response']['question_message_id'],ref)
        self.assertEqual(context['customer_response']['id'],'unsure')
        self.assertEqual(Ticket.objects.count(),0)

    def test_no_power_does_not_run_remote_throughput(self):
        before=self.service.diagnostic_runs.count()
        result=self.choose('no_power')
        self.assertEqual(result.status_code,200,result.content)
        self.assertIsNone(result.json()['diagnostic'])
        self.assertEqual(self.service.diagnostic_runs.count(),before)

    def test_slow_internet_uses_signal_metrics(self):
        from customers.models import InternetService
        self.service=InternetService.objects.get(service_identifier='DEMO-SERVICE-002')
        self.select('en')
        result=self.choose('slow')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['intent'],'SLOW_INTERNET')
        self.assertEqual(result.json()['diagnostic']['result_code'],'SIGNAL_DEGRADED')
        self.assertIsNotNone(result.json()['diagnostic']['metrics']['rssi_dbm'])

    def test_other_service_conversation_is_not_authorized(self):
        from customers.models import InternetService
        other=InternetService.objects.get(service_identifier='DEMO-SERVICE-002')
        conversation=Conversation.objects.create(customer=other.customer,internet_service=other)
        self.select('en')
        self.assertEqual(self.choose('human',conversation.pk).status_code,400)
        self.assertFalse(conversation.messages.exists())
        self.assertEqual(Ticket.objects.count(),0)

    def test_client_cannot_supply_operational_flags_or_forged_text(self):
        self.select('en')
        for selection,text in [({'id':'human','question_message_id':None,'authorize_ticket':True},''),
                               ({'id':'human','question_message_id':None},'I checked everything')]:
            response=self.client.post('/api/chat/turn/',{'request_id':str(uuid.uuid4()),'service_id':self.service.pk,
                'message':text,'quick_reply':json.dumps(selection)},HTTP_X_CSRFTOKEN=self.csrf)
            self.assertEqual(response.status_code,400)
        self.assertEqual(Message.objects.count(),0)
