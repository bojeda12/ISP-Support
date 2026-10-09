import uuid

from django.core.validators import MinValueValidator
from django.db import models


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    external_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.external_id})"


class InternetService(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Canceled"

    class ConnectivityStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"
        DEGRADED = "DEGRADED", "Degraded"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="services")
    service_identifier = models.CharField(max_length=100, unique=True)
    plan_name = models.CharField(max_length=100)
    advertised_download_mbps = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=12, choices=Status, default=Status.ACTIVE)
    connectivity_status = models.CharField(
        max_length=12, choices=ConnectivityStatus, default=ConnectivityStatus.UNKNOWN
    )
    suspension_reason = models.TextField(blank=True)
    cpe_identifier = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(advertised_download_mbps__gt=0), name="service_positive_download"
        )]

    def __str__(self):
        return self.service_identifier
