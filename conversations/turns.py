"""Turno multipart atómico: una foto, una pregunta, una respuesta e idempotencia."""
import hashlib
import json
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import ChatTurn
from .services import chat, ensure_session


def submit_turn(*, session, request_id, message='', conversation=None, language=None, initial_language=None, upload=None, quick_reply=None):
    ensure_session(session)
    raw = b''
    if upload:
        from .photos import validate_photo
        validate_photo(upload)
        upload.seek(0)
        raw = upload.read()
        upload.seek(0)
    submission = [message,getattr(conversation,'pk',None),language,initial_language]
    if quick_reply is not None:
        submission.append(quick_reply)
    fingerprint = hashlib.sha256(json.dumps(submission,ensure_ascii=False,sort_keys=True).encode()+raw).hexdigest()
    stored_keys = []
    try:
        with transaction.atomic():
            prior = ChatTurn.objects.select_for_update().filter(session=session,request_id=request_id).first()
            if prior:
                if prior.fingerprint != fingerprint:
                    raise ValidationError('Request ID was already used with a different submission.')
                from knowledge.services import replay_customer_payload
                return replay_customer_payload(prior.response,session)
            turn = ChatTurn.objects.create(session=session,request_id=request_id,fingerprint=fingerprint)
            selected = None
            if quick_reply is not None:
                from .quick_replies import resolve
                from .models import Conversation
                if conversation:
                    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
                    if (conversation.customer_id != session.internet_service.customer_id or
                            conversation.internet_service_id != session.internet_service_id):
                        raise ValidationError('Conversation is not available.')
                selected = resolve(quick_reply, conversation, language or getattr(conversation,'language',None) or initial_language or 'en')
                # El cliente no puede añadir afirmaciones a una opción estructurada.
                if message and message != selected['message']:
                    raise ValidationError('Quick reply text does not match the selected option.')
                message = selected['message']
            result = chat(session=session,message=message,conversation=conversation,language=language,
                initial_language=initial_language,upload=upload,stored_keys=stored_keys,customer_response=selected)
            result['request_id'] = str(request_id)
            from .models import Message
            customer_message = Message.objects.filter(conversation_id=result['conversation_id'],sender=Message.Sender.CUSTOMER).order_by('-pk').first()
            customer_message.metadata = {**customer_message.metadata,'request_id':str(request_id)}
            if selected:
                customer_message.metadata['quick_reply'] = selected
            customer_message.save(update_fields=['metadata'])
            turn.response = result
            turn.save(update_fields=['response'])
            return result
    except Exception:
        if stored_keys:
            from .photos import photo_storage
            storage = photo_storage()
            for key in stored_keys:
                storage.delete(key)
        raise
