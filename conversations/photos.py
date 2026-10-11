"""Almacenamiento privado y análisis visual sin efectos de diagnóstico."""

import logging
import warnings
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError as SchemaValidationError
from rest_framework.exceptions import ValidationError

from .ai import ProviderError, get_provider
from .models import ConversationPhoto, Message
from .services import ensure_session, trace_logger
from .visual_schema import VisualAnalysis

logger = logging.getLogger(__name__)


class PrivateStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError("Private photos have no public storage URL.")


def photo_storage():
    return PrivateStorage(location=settings.PRIVATE_MEDIA_ROOT, file_permissions_mode=0o600)


def validate_photo(upload) -> tuple[bytes, int, int]:
    if not upload or upload.size > settings.PHOTO_MAX_BYTES:
        raise ValidationError({"photo": "Photo exceeds the 5 MiB limit or is missing."})
    if Path(upload.name).suffix.lower() in {'.heic', '.heif'} or upload.content_type in {'image/heic', 'image/heif', 'image/heic-sequence', 'image/heif-sequence'}:
        raise ValidationError({"photo": "HEIC/HEIF decoding is unavailable in this demo. Export the photo as JPEG, PNG or WebP and try again."})
    formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    suffixes = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}, "WEBP": {".webp"}}
    expected = formats.get(upload.content_type)
    if expected is None or Path(upload.name).suffix.lower() not in suffixes[expected]:
        raise ValidationError({"photo": "Only JPEG, PNG and WebP photos are supported. Convert HEIC/HEIF to one of these formats."})
    raw = upload.read(settings.PHOTO_MAX_BYTES + 1)
    if len(raw) > settings.PHOTO_MAX_BYTES:
        raise ValidationError({"photo": "Photo exceeds the 5 MiB limit."})
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if (image.format != expected or width * height > settings.PHOTO_MAX_PIXELS
                        or max(width, height) > settings.PHOTO_MAX_DIMENSION or getattr(image, "n_frames", 1) != 1):
                    raise ValidationError({"photo": "Invalid format, dimensions or animated image."})
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                # Copiar píxeles elimina EXIF, GPS, perfiles y posibles datos añadidos al archivo.
                clean = Image.frombytes("RGB", normalized.size, normalized.tobytes())
                output = BytesIO()
                clean.save(output, format="JPEG", quality=85)
                encoded = output.getvalue()
                if len(encoded) > settings.PHOTO_MAX_BYTES:
                    raise ValidationError({"photo": "Normalized photo is too large."})
                return encoded, clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError({"photo": "The file is not a valid supported photo."}) from error


def photo_payload(photo) -> dict:
    english = photo.conversation.language == "en"
    actions = {
        "CHECK_ACCESSIBLE_CONNECTIONS": ("Revisar únicamente conexiones accesibles, sin manipular cableado eléctrico.", "Check only safely accessible connections; do not handle electrical wiring."),
        "CHECK_INDICATORS": ("Observar los indicadores y consultar el manual del equipo.", "Observe the indicators and consult the equipment manual."),
        "TAKE_CLEARER_PHOTO": ("Enviar una foto más clara sin mostrar credenciales ni datos personales.", "Send a clearer photo without credentials or personal data."),
        "CONTACT_SUPPORT": ("Consultar con soporte técnico; no subir al techo ni mover antenas.", "Contact technical support; do not climb onto the roof or move antennas."),
    }
    return {
        "id": str(photo.pk), "conversation_id": photo.conversation_id,
        "message_id": photo.message_id, "mime_type": photo.mime_type,
        "width": photo.width, "height": photo.height, "size_bytes": photo.size_bytes,
        "content_url": reverse("api:photo-content", args=[photo.pk]),
        "status": photo.status, "provider": photo.provider,
        "simulated": photo.provider == "demo", "analysis": photo.analysis,
        "recommendations": [actions[action][int(english)] for action in photo.analysis.get("recommended_actions", []) if action in actions],
        "disclaimer": "A photograph cannot confirm connectivity or electrical safety." if english else "Una fotografía no confirma conectividad ni seguridad eléctrica.",
        "created_at": photo.created_at.isoformat(),
    }


def upload_and_analyze(*, session, conversation, upload, message=None, emit_reply=True, question='', stored_keys=None):
    ensure_session(session)
    if (conversation.customer_id != session.internet_service.customer_id or
            conversation.internet_service_id != session.internet_service_id or conversation.status != "OPEN"):
        raise ValidationError("Conversation is not available.")
    image, width, height = validate_photo(upload)
    photo = ConversationPhoto(
        conversation=conversation, mime_type="image/jpeg", size_bytes=len(image),
        width=width, height=height, provider=settings.AI_PROVIDER,
    )
    storage = photo_storage()
    key = storage.save(f"photos/{photo.pk.hex}.jpg", ContentFile(image))
    if stored_keys is not None:
        stored_keys.append(key)
    try:
        with transaction.atomic():
            if message is None:
                message = Message.objects.create(
                    conversation=conversation, sender=Message.Sender.CUSTOMER,
                    content="Photo uploaded." if conversation.language == "en" else "Fotografía enviada.")
            message.metadata = {**message.metadata,'photo_id':str(photo.pk),'type':'photo'}
            message.save(update_fields=['metadata'])
            photo.message, photo.storage_key = message, key
            photo.save()
    except Exception:
        # Compensación del archivo si falla la transacción; el error original se propaga.
        storage.delete(key)
        raise
    provider = None
    try:
        provider = get_provider()
        kwargs = {'image':image,'mime_type':photo.mime_type,'language':conversation.language}
        if question:
            kwargs['question'] = question[:2000]
        analysis = VisualAnalysis.model_validate(provider.analyze_photo(**kwargs))
        photo.analysis = analysis.model_dump(mode="json")
        photo.status = ConversationPhoto.Status.COMPLETED
    except (ProviderError, SchemaValidationError, TimeoutError) as error:
        logger.warning("Photo provider failure photo=%s category=%s", photo.pk, type(error).__name__)
        english = conversation.language == "en"
        photo.analysis = {
            "observations": [],
            "uncertainties": ["Analysis unavailable; no conclusions can be drawn." if english else
                              "Análisis no disponible; no se pueden sacar conclusiones."],
            "recommended_actions": ["CONTACT_SUPPORT"], "connectivity_confirmed": False,
        }
        photo.status = ConversationPhoto.Status.FAILED
    if settings.DEBUG and settings.DJANGO_ENV == 'development':
        trace_logger.info('photo_runtime %s', {
            'effective_provider': settings.AI_PROVIDER if settings.AI_PROVIDER in {'demo', 'openai'} else 'unknown',
            'external_call_attempted': getattr(provider, 'external_call_attempted', False) is True,
            'fallback_used': photo.status == ConversationPhoto.Status.FAILED,
            'response_source': 'photo_error' if photo.status == ConversationPhoto.Status.FAILED else
                'demo_vision' if photo.provider == 'demo' else 'openai_vision',
        })
    with transaction.atomic():
        photo.save(update_fields=["status", "analysis"])
        disclaimer = "A photograph does not confirm connectivity or electrical safety." if conversation.language == "en" else "Una fotografía no confirma conectividad ni seguridad eléctrica."
        if photo.provider == "demo":
            disclaimer = ("SIMULATED ANALYSIS. " if conversation.language == "en" else "ANÁLISIS SIMULADO. ") + disclaimer
        if emit_reply:
            Message.objects.create(
                conversation=conversation, sender=Message.Sender.ASSISTANT, content=disclaimer,
                metadata={"photo_id": str(photo.pk), "type": "photo_analysis", "status": photo.status})
    return photo
