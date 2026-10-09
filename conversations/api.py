from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import DemoSessionAuthentication
from .serializers import ChatSerializer
from .services import chat


class ChatView(APIView):
    authentication_classes = [DemoSessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChatSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        web_session = request.session.get("demo_session_id") == str(request.auth.pk)
        initial = serializer.validated_data.get("conversation") is None
        if web_session and initial and request.session.get("demo_preferred_language") not in {"en", "es"}:
            raise ValidationError("Confirm your preferred language before starting a new chat.")
        try:
            result = chat(session=request.auth, message=serializer.validated_data["message"],
                          conversation=serializer.validated_data.get("conversation"),
                          language=serializer.validated_data.get("language"),
                          initial_language=request.session.get("demo_preferred_language") if web_session and initial else None)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        if request.session.get("demo_session_id") == str(request.auth.pk):
            request.session["demo_conversation_id"] = result["conversation_id"]
        return Response(result)
