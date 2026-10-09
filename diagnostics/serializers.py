from collections.abc import Mapping

from rest_framework import serializers

from conversations.models import Conversation
from customers.models import InternetService
from .models import DiagnosticRun


class RunDiagnosticSerializer(serializers.Serializer):
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=InternetService.objects.all(), pk_field=serializers.IntegerField(min_value=1)
    )
    conversation_id = serializers.PrimaryKeyRelatedField(
        queryset=Conversation.objects.all(), required=False, allow_null=True,
        pk_field=serializers.IntegerField(min_value=1),
    )

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field." for key in unknown})
        return super().to_internal_value(data)

    def validate(self, attrs):
        service = attrs["service_id"]
        if not hasattr(service, "simulation_state"):
            raise serializers.ValidationError({"service_id": "Service is not enrolled in the demo simulator."})
        conversation = attrs.get("conversation_id")
        if conversation and (conversation.customer_id != service.customer_id or
                             conversation.internet_service_id not in (None, service.pk)):
            raise serializers.ValidationError({"conversation_id": "Conversation does not match the service."})
        return attrs


class DiagnosticRunSerializer(serializers.ModelSerializer):
    service_id = serializers.IntegerField(source="internet_service_id")

    class Meta:
        model = DiagnosticRun
        fields = ("id", "service_id", "conversation_id", "scenario", "result", "result_code",
                  "metrics", "assessment", "source", "started_at", "completed_at", "created_at")
        read_only_fields = fields
