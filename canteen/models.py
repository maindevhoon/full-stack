from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class MenuItem(models.Model):
    class Category(models.TextChoices):
        MEALS = "meals", "Meals"
        SNACKS = "snacks", "Snacks"
        DRINKS = "drinks", "Drinks"
        OTHER = "other", "Other"

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=16, choices=Category, default=Category.OTHER)
    price = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    available = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="menu_price_nonnegative")
        ]

    def __str__(self):
        return self.name


class PickupSlot(models.Model):
    start_at = models.DateTimeField(unique=True)
    end_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    reserved_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["start_at"]
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gte=1), name="slot_positive_capacity"),
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="slot_valid_interval"),
            models.CheckConstraint(
                condition=Q(reserved_count__lte=F("capacity")), name="slot_reservations_within_capacity"
            ),
        ]

    @property
    def remaining(self):
        return self.capacity - self.reserved_count

    @property
    def is_open(self):
        return self.start_at > timezone.now() and self.remaining > 0

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "End time must be later than start time."})
        if self.capacity is not None and self.reserved_count > self.capacity:
            raise ValidationError({"capacity": "Capacity cannot be lower than existing reservations."})

    def __str__(self):
        start = timezone.localtime(self.start_at)
        end = timezone.localtime(self.end_at)
        return f"{start:%d %b, %H:%M}–{end:%H:%M}"


class Order(models.Model):
    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        COLLECTED = "collected", "Collected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    slot = models.ForeignKey(PickupSlot, on_delete=models.PROTECT, related_name="orders")
    token = models.CharField(max_length=15, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status, default=Status.PLACED)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    collected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_nonnegative"),
            models.CheckConstraint(
                condition=Q(status__in=["placed", "preparing", "ready", "collected"]),
                name="order_valid_status",
            ),
            models.CheckConstraint(
                condition=Q(status="collected", collected_at__isnull=False)
                | (~Q(status="collected") & Q(collected_at__isnull=True)),
                name="order_collection_timestamp_matches_status",
            ),
        ]

    def __str__(self):
        return self.token


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    item_name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["order", "menu_item"], name="one_line_per_order_item"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="line_positive_quantity"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="line_price_nonnegative"),
        ]

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} × {self.item_name}"
