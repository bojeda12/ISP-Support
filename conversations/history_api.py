from rest_framework import serializers
from rest_framework.response import Response

from diagnostics.models import DiagnosticRun
from tickets.models import Ticket
from .instructions import find_instruction
from .media_api import AuthorizedMediaView
from .models import ConversationPhoto
from .photos import photo_payload
from .replies import diagnostic_payload
from knowledge.services import historical_customer_text


class ConversationMessagesView(AuthorizedMediaView):
    def get(self, request, conversation_id):
        conversation = self.conversation(request, conversation_id)
        messages = conversation.messages.order_by("-pk")
        before = request.query_params.get("before")
        if before is not None:
            try:
                before = int(before)
                if before < 1:
                    raise ValueError
            except (ValueError, TypeError):
                raise serializers.ValidationError("Invalid message cursor.")
            messages = messages.filter(pk__lt=before)
        rows = list(messages[:51])
        page = list(reversed(rows[:50]))
        data = []
        from .quick_replies import offers
        latest_assistant = conversation.messages.filter(sender='assistant').order_by('-pk').first()
        for message in page:
            meta = message.metadata
            diagnostic = DiagnosticRun.objects.filter(pk=meta.get("diagnostic_id"), conversation=conversation).first()
            ticket = Ticket.objects.filter(pk=meta["ticket_id"], conversation=conversation).first() if meta.get("ticket_id") else None
            photo = ConversationPhoto.objects.filter(pk=meta["photo_id"], conversation=conversation).first() if meta.get("photo_id") else None
            # Únicamente claves de presentación generadas por el backend.
            display_key = meta.get("display_key") if meta.get("display_key") in {"CPE_ESCALATED", "CPE_FOLLOW_UP"} else None
            data.append({
                "id": message.pk, "sender": message.sender, "content": historical_customer_text(message),
                "created_at": message.created_at.isoformat(),
                'request_id':meta.get('request_id'),
                'operation_outcome':meta.get('operation_outcome'),
                'quick_replies': offers(message, conversation.language) if latest_assistant and message.pk == latest_assistant.pk else [],
                "diagnostic": diagnostic_payload(diagnostic, conversation.language, display_key) if diagnostic else None,
                "ticket": {"id": str(ticket.pk), "number": ticket.number, "status": ticket.status} if ticket else None,
                "images": [entry for image_id in meta.get("image_ids", []) if (entry := find_instruction(image_id))],
                "photo": photo_payload(photo) if photo else None,
            })
        return Response({"conversation_id": conversation.pk, "language": conversation.language,
                         "messages": data, "next_before": rows[49].pk if len(rows) > 50 else None})
