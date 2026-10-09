from django.core.exceptions import ValidationError
from django.db import models


class Conversation(models.Model):
    class Language(models.TextChoices):
        SPANISH = "es", "Español"
        ENGLISH = "en", "Inglés"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        CLOSED = "CLOSED", "Cerrada"

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
        CUSTOMER = "customer", "Cliente"
        ASSISTANT = "assistant", "Asistente"
        TECHNICIAN = "technician", "Técnico"
        SYSTEM = "system", "Sistema"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=12, choices=Sender)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.sender}: {self.content[:60]}"
