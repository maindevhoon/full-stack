from collections.abc import Mapping
from decimal import Decimal
from secrets import compare_digest, token_hex

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import MenuItem, Order, OrderItem, PickupSlot


MAX_ITEM_QUANTITY = 20
MAX_CART_LINES = 30


class OrderError(ValueError):
    """A placed order or workflow change violates a canteen rule."""


def _validate_cart(cart):
    if not isinstance(cart, Mapping) or not cart:
        raise OrderError("Add at least one item to your cart.")
    if len(cart) > MAX_CART_LINES:
        raise OrderError(f"An order can contain at most {MAX_CART_LINES} different items.")
    for item_id, quantity in cart.items():
        if (
            type(item_id) is not int
            or item_id <= 0
            or type(quantity) is not int
            or not 1 <= quantity <= MAX_ITEM_QUANTITY
        ):
            raise OrderError(f"Enter quantities from 1 to {MAX_ITEM_QUANTITY} for valid items.")


def _new_pickup_token():
    for _ in range(5):
        token = "CP-" + token_hex(6).upper()
        if not Order.objects.filter(token=token).exists():
            return token
    raise OrderError("Could not make a pickup token. Try again.")


def place_order(user, slot_id, cart):
    if not user.is_authenticated or not user.is_active or user.is_staff:
        raise OrderError("Sign in with an active student account to place an order.")
    if type(slot_id) is not int or slot_id <= 0:
        raise OrderError("Choose a valid pickup slot.")
    _validate_cart(cart)

    with transaction.atomic():
        claimed = PickupSlot.objects.filter(
            pk=slot_id,
            start_at__gt=timezone.now(),
            reserved_count__lt=F("capacity"),
        ).update(reserved_count=F("reserved_count") + 1)
        if not claimed:
            raise OrderError("This pickup slot is full or has already started. Choose another.")

        menu = MenuItem.objects.in_bulk(cart.keys())
        for item_id in cart:
            item = menu.get(item_id)
            if item is None or not item.available:
                name = item.name if item is not None else "An item in your cart"
                raise OrderError(f"{name} is no longer available.")

        lines = [
            OrderItem(menu_item=menu[item_id], item_name=menu[item_id].name,
                      unit_price=menu[item_id].price, quantity=quantity)
            for item_id, quantity in cart.items()
        ]
        order = Order.objects.create(
            user=user,
            slot_id=slot_id,
            token=_new_pickup_token(),
            total=sum((line.line_total for line in lines), Decimal("0.00")),
        )
        for line in lines:
            line.order = order
        OrderItem.objects.bulk_create(lines)
        return order


NEXT_STATUS = {
    Order.Status.PLACED: Order.Status.PREPARING,
    Order.Status.PREPARING: Order.Status.READY,
    Order.Status.READY: Order.Status.COLLECTED,
}


def transition_order(order_id, target, token=None):
    try:
        desired = Order.Status(target)
    except (ValueError, TypeError) as exc:
        raise OrderError("Choose a valid order status.") from exc

    with transaction.atomic():
        order = Order.objects.filter(pk=order_id).first()
        if order is None:
            raise OrderError("Order not found.")
        if order.status == Order.Status.COLLECTED:
            raise OrderError("This order has already been collected.")
        if NEXT_STATUS.get(order.status) != desired:
            raise OrderError("Orders must move from Placed to Preparing, Ready, and then Collected.")
        if desired == Order.Status.COLLECTED:
            supplied = token.strip().upper().encode() if isinstance(token, str) else b""
            if not compare_digest(order.token.encode(), supplied):
                raise OrderError("That pickup token does not match this order.")
            order.collected_at = timezone.now()
        order.status = desired
        order.save(update_fields=["status", "collected_at", "updated_at"])
        return order
