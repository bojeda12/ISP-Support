from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import DemoSessionAuthentication
from .serializers import ChatSerializer, ChatTurnSerializer
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
        if not (settings.DEBUG and settings.DJANGO_ENV == 'development'):
            result.pop('debug', None)
        return Response(result)


class ChatTurnView(ChatView):
    from rest_framework.parsers import MultiPartParser
    parser_classes = [MultiPartParser]

    def initialize_request(self,request,*args,**kwargs):
        from .upload_handlers import BoundedPhotoUploadHandler
        request.upload_handlers = [BoundedPhotoUploadHandler(request)]
        return super().initialize_request(request,*args,**kwargs)

    def post(self,request):
        from .turns import submit_turn
        from django.db import OperationalError, IntegrityError
        data = request.data
        if getattr(request._request,'photo_too_large',False):
            return Response({'photo':'Photo exceeds the 5 MiB limit.'},status=413)
        if any(len(data.getlist(key)) != 1 for key in data) or len(request.FILES.getlist('photo')) > 1:
            raise ValidationError('Duplicate multipart fields are not allowed.')
        serializer = ChatTurnSerializer(data=data,context={'request':request})
        serializer.is_valid(raise_exception=True)
        attrs = serializer.validated_data
        web_session = request.session.get('demo_session_id') == str(request.auth.pk)
        initial = attrs.get('conversation') is None
        if web_session and initial and request.session.get('demo_preferred_language') not in {'en','es'}:
            raise ValidationError('Confirm your preferred language before starting a new chat.')
        try:
            result = submit_turn(session=request.auth,request_id=attrs['request_id'],message=attrs['message'],
                quick_reply=attrs.get('quick_reply'),
                conversation=attrs.get('conversation'),language=attrs.get('language'),upload=attrs.get('photo'),
                initial_language=request.session.get('demo_preferred_language') if web_session and initial else None)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        except (OperationalError,IntegrityError):
            return Response({'detail':'Turn could not be confirmed. Review history and retry with the same request ID.'},status=409)
        if web_session:
            request.session['demo_conversation_id'] = result['conversation_id']
        if not (settings.DEBUG and settings.DJANGO_ENV == 'development'):
            result.pop('debug', None)
        return Response(result)
