from django.http import FileResponse
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import DemoSessionAuthentication
from .instructions import ASSET_ROOT, catalog, find_instruction
from .models import Conversation, ConversationPhoto
from .photos import photo_payload, photo_storage, upload_and_analyze
from .upload_handlers import BoundedPhotoUploadHandler


class AuthorizedMediaView(APIView):
    authentication_classes = [DemoSessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def conversation(self, request, conversation_id):
        return get_object_or_404(
            Conversation, pk=conversation_id,
            customer_id=request.auth.internet_service.customer_id,
            internet_service_id=request.auth.internet_service_id,
        )

    def photo(self, request, photo_id):
        return get_object_or_404(
            ConversationPhoto, pk=photo_id,
            conversation__customer_id=request.auth.internet_service.customer_id,
            conversation__internet_service_id=request.auth.internet_service_id,
        )


def private_response(file, content_type):
    response = FileResponse(file, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


class InstructionCatalogView(AuthorizedMediaView):
    def get(self, request):
        language = request.query_params.get("language", "es")
        if language not in {"es", "en"}:
            raise serializers.ValidationError("Unsupported language.")
        return Response({"images": catalog(language)})


class InstructionImageView(AuthorizedMediaView):
    def get(self, request, image_id):
        from django.http import Http404
        entry = find_instruction(image_id)
        if entry is None:
            raise Http404
        if not (ASSET_ROOT / entry["path"]).is_file():
            raise Http404("Instruction image is unavailable.")
        # La ruta procede exclusivamente del catálogo versionado, nunca del cliente.
        return private_response((ASSET_ROOT / entry["path"]).open("rb"), entry["mime_type"])


class ConversationPhotosView(AuthorizedMediaView):
    parser_classes = [MultiPartParser]

    def initialize_request(self, request, *args, **kwargs):
        request.upload_handlers = [BoundedPhotoUploadHandler(request)]
        return super().initialize_request(request, *args, **kwargs)

    def get(self, request, conversation_id):
        conversation = self.conversation(request, conversation_id)
        try:
            after_id = request.query_params.get("after")
            after = ConversationPhoto.objects.get(pk=after_id, conversation=conversation) if after_id else None
        except (ConversationPhoto.DoesNotExist, DjangoValidationError, ValueError, TypeError):
            raise serializers.ValidationError("Invalid photo cursor.")
        photos = conversation.photos.order_by("created_at", "pk")
        if after:
            from django.db.models import Q
            photos = photos.filter(Q(created_at__gt=after.created_at) | Q(created_at=after.created_at, pk__gt=after.pk))
        items = list(photos[:51])
        return Response({"photos": [photo_payload(photo) for photo in items[:50]],
                         "next_after": str(items[49].pk) if len(items) > 50 else None})

    def post(self, request, conversation_id):
        conversation = self.conversation(request, conversation_id)
        data = request.data
        if getattr(request._request, "photo_too_large", False):
            return Response({"photo": "Photo exceeds the 5 MiB limit."}, status=413)
        if set(data) != {"photo"} or len(request.FILES.getlist("photo")) != 1:
            raise serializers.ValidationError("Supply exactly one photo file; URLs and extra fields are not accepted.")
        photo = upload_and_analyze(session=request.auth, conversation=conversation, upload=request.FILES.get("photo"))
        return Response(photo_payload(photo), status=201)


class PhotoDetailView(AuthorizedMediaView):
    def get(self, request, photo_id):
        return Response(photo_payload(self.photo(request, photo_id)))


class PhotoContentView(AuthorizedMediaView):
    def get(self, request, photo_id):
        photo = self.photo(request, photo_id)
        return private_response(photo_storage().open(photo.storage_key, "rb"), photo.mime_type)
