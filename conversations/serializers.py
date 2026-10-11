from collections.abc import Mapping

from django.conf import settings
from rest_framework import serializers

from .models import Conversation


class ChatSerializer(serializers.Serializer):
    message = serializers.CharField(trim_whitespace=True)
    conversation_id = serializers.IntegerField(min_value=1, required=False)
    service_id = serializers.IntegerField(min_value=1, required=False)
    language = serializers.ChoiceField(choices=["es", "en"], required=False)

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({key: "Unknown field." for key in unknown})
        return super().to_internal_value(data)

    def validate_message(self, value):
        if len(value) > settings.CHAT_MAX_MESSAGE_LENGTH:
            raise serializers.ValidationError("Message is too long.")
        return value

    def validate(self, attrs):
        if ("conversation_id" in attrs) == ("service_id" in attrs):
            raise serializers.ValidationError("Supply exactly one of conversation_id or service_id.")
        session = self.context["request"].auth
        if "service_id" in attrs and attrs["service_id"] != session.internet_service_id:
            raise serializers.ValidationError({"service_id": "Service is not authorized."})
        if "conversation_id" in attrs:
            conversation = Conversation.objects.filter(
                pk=attrs["conversation_id"], customer_id=session.internet_service.customer_id,
                internet_service_id=session.internet_service_id, status=Conversation.Status.OPEN,
            ).first()
            if conversation is None:
                raise serializers.ValidationError({"conversation_id": "Conversation is not available."})
            attrs["conversation"] = conversation
        return attrs


class ChatTurnSerializer(ChatSerializer):
    message = serializers.CharField(trim_whitespace=True,required=False,allow_blank=True,default='')
    photo = serializers.FileField(required=False)
    request_id = serializers.UUIDField()
    quick_reply = serializers.JSONField(required=False)

    def validate(self,attrs):
        attrs = super().validate(attrs)
        if not attrs.get('message') and not attrs.get('photo') and not attrs.get('quick_reply'):
            raise serializers.ValidationError('Supply text, a photograph, or both.')
        return attrs
