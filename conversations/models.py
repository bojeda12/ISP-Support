import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Conversation(models.Model):
    class Language(models.TextChoices):
        SPANISH = "es", "Spanish"
        ENGLISH = "en", "English"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="conversations")
    internet_service = models.ForeignKey(
        "customers.InternetService", on_delete=models.PROTECT,
        related_name="conversations", null=True, blank=True
    )
    language = models.CharField(max_length=2, choices=Language, default=Language.SPANISH)
    status = models.CharField(max_length=10, choices=Status, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.internet_service_id and self.customer_id != self.internet_service.customer_id:
            raise ValidationError({"internet_service": "Service must belong to the customer."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Conversation {self.pk} - {self.customer}"


class Message(models.Model):
    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        ASSISTANT = "assistant", "Assistant"
        TECHNICIAN = "technician", "Technician"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=12, choices=Sender)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.sender}: {self.content[:60]}"


class DemoChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    internet_service = models.ForeignKey("customers.InternetService", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    class Meta:
        permissions = [("use_demo_chat", "Can issue and use fictional chat sessions")]


class ConversationPhoto(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name="photos")
    message = models.OneToOneField(Message, on_delete=models.PROTECT, related_name="photo")
    storage_key = models.CharField(max_length=100, editable=False)
    mime_type = models.CharField(max_length=20)
    size_bytes = models.PositiveIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    provider = models.CharField(max_length=20)
    analysis = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ChatTurn(models.Model):
    """Clave idempotente por sesión para envíos multipart atómicos."""
    session = models.ForeignKey(DemoChatSession, on_delete=models.CASCADE)
    request_id = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['session','request_id'], name='unique_session_chat_turn')]
