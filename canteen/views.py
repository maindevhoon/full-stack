from collections import Counter
from datetime import date
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login as sign_in
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    MAX_QUANTITY,
    CheckoutForm,
    MenuItemForm,
    OrderQuantityForm,
    PickupSlotForm,
    StudentRegistrationForm,
)
from .models import MenuItem, Order, PickupSlot
from .services import MAX_CART_LINES, NEXT_STATUS, OrderError, place_order, transition_order

CART_SESSION_KEY = "canteen_cart"


def for_role(staff=False):
    def decorate(view):
        @login_required
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if request.user.is_staff != staff:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return guarded

    return decorate


def register(request):
    if request.user.is_authenticated:
        return redirect("menu")
    form = StudentRegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        sign_in(request, user)
        messages.success(request, "Your student account is ready.")
        return redirect("menu")
    return render(request, "registration/register.html", {"form": form})


def read_cart(request):
    return {
        int(item_id): quantity
        for item_id, quantity in request.session.get(CART_SESSION_KEY, {}).items()
        if isinstance(item_id, str)
        and item_id.isascii()
        and item_id.isdigit()
        and type(quantity) is int
        and 1 <= quantity <= MAX_QUANTITY
    }


def save_cart(request, selection):
    request.session[CART_SESSION_KEY] = {
        str(key): quantity for key, quantity in selection.items()
    }


def cart_context(selection):
    items = MenuItem.objects.in_bulk(selection)
    lines = []
    for item_id, quantity in selection.items():
        item = items.get(item_id)
        lines.append({
            "id": item_id,
            "name": item.name if item else "Removed item",
            "available": bool(item and item.available),
            "quantity": quantity,
            "price": item.price if item else None,
            "subtotal": item.price * quantity if item else None,
        })
    return {
        "lines": lines,
        "total": sum((line["subtotal"] or Decimal("0") for line in lines), Decimal("0")),
        "has_unavailable": any(not line["available"] for line in lines),
    }


def upcoming_slots():
    return PickupSlot.objects.filter(start_at__gt=timezone.now()).order_by("start_at", "pk")


@login_required
def menu(request):
    if request.user.is_staff:
        return redirect("staff_queue")
    category = request.GET.get("category", "")
    categories = list(MenuItem.Category.choices)
    if category not in dict(categories):
        category = ""
    items = MenuItem.objects.all().order_by("-available", "category", "name")
    if category:
        items = items.filter(category=category)
    next_slot = upcoming_slots().filter(reserved_count__lt=F("capacity")).first()
    return render(request, "canteen/menu.html", {
        "items": items, "categories": categories, "category": category,
        "next_slot": next_slot, "cart_items": sum(read_cart(request).values()),
        "max_quantity": MAX_QUANTITY,
    })


@for_role()
def cart(request):
    return render(request, "canteen/cart.html", {**cart_context(read_cart(request)), "max_quantity": MAX_QUANTITY})


@for_role()
@require_POST
def add_to_cart(request, item_id):
    item = get_object_or_404(MenuItem, pk=item_id)
    form = OrderQuantityForm(request.POST)
    selection = read_cart(request)
    if not item.available:
        messages.error(request, f"{item.name} is currently sold out.")
    elif not form.is_valid() or form.cleaned_data["quantity"] == 0:
        messages.error(request, f"Enter a quantity from 1 to {MAX_QUANTITY}.")
    elif item_id not in selection and len(selection) >= MAX_CART_LINES:
        messages.error(request, f"The cart can hold up to {MAX_CART_LINES} different items.")
    else:
        quantity = selection.get(item_id, 0) + form.cleaned_data["quantity"]
        if quantity > MAX_QUANTITY:
            messages.error(request, f"The cart can hold up to {MAX_QUANTITY} of each item.")
        else:
            selection[item_id] = quantity
            save_cart(request, selection)
            messages.success(request, f"{item.name} added to your cart.")
    return redirect("menu")


@for_role()
@require_POST
def update_cart(request, item_id):
    selection = read_cart(request)
    form = OrderQuantityForm(request.POST)
    if item_id not in selection:
        raise PermissionDenied
    if not form.is_valid():
        messages.error(request, f"Enter a quantity from 0 to {MAX_QUANTITY}.")
    else:
        quantity = form.cleaned_data["quantity"]
        if quantity == 0:
            selection.pop(item_id)
            save_cart(request, selection)
        elif MenuItem.objects.filter(pk=item_id, available=True).exists():
            selection[item_id] = quantity
            save_cart(request, selection)
        else:
            messages.error(request, "This item is unavailable. Remove it before checkout.")
    return redirect("cart")


@for_role()
def checkout(request):
    selection = read_cart(request)
    context = cart_context(selection)
    if not selection or context["has_unavailable"]:
        messages.error(request, "Your cart needs at least one item, and all items must be available.")
        return redirect("cart")
    windows = upcoming_slots()
    bookable = windows.filter(reserved_count__lt=F("capacity"))
    form = CheckoutForm(request.POST if request.method == "POST" else None, slots=bookable)
    if request.method == "POST" and form.is_valid():
        try:
            order = place_order(request.user, form.cleaned_data["slot"].pk, selection)
        except OrderError as error:
            form.add_error(None, str(error))
        else:
            save_cart(request, {})
            messages.success(request, "Order placed. Your pickup token is below.")
            return redirect("order_detail", order_id=order.pk)
    return render(request, "canteen/checkout.html", {
        **context, "form": form, "slots": windows, "has_bookable": bookable.exists(),
    })


@for_role()
def order_history(request):
    orders = request.user.orders.select_related("slot").order_by("-created_at", "-pk")
    return render(request, "canteen/orders.html", {"orders": orders})


@for_role()
def order_detail(request, order_id):
    orders = Order.objects.filter(user=request.user).select_related("slot").prefetch_related("items")
    order = get_object_or_404(orders, pk=order_id)
    state = list(Order.Status.values).index(order.status)
    progress = [
        {"label": label, "done": index < state, "current": index == state}
        for index, label in enumerate(Order.Status.labels)
    ]
    return render(request, "canteen/order_detail.html", {"order": order, "progress": progress})


@for_role(staff=True)
def staff_queue(request):
    status = request.GET.get("status", "")
    valid_statuses = dict(Order.Status.choices)
    if status not in valid_statuses:
        status = ""
    orders = Order.objects.select_related("slot", "user").prefetch_related("items").order_by(
        "slot__start_at", "created_at", "pk"
    )
    counts = Counter(Order.objects.values_list("status", flat=True))
    if status:
        orders = orders.filter(status=status)
    else:
        orders = orders.exclude(status=Order.Status.COLLECTED)
    entries = [
        {"order": order, "next": NEXT_STATUS.get(order.status)}
        for order in orders
    ]
    filters = [
        {"value": value, "label": label, "count": counts[value]}
        for value, label in Order.Status.choices
    ]
    return render(request, "canteen/staff_queue.html", {
        "entries": entries, "filters": filters, "status": status,
        "active_count": sum(counts[value] for value in NEXT_STATUS),
    })


@for_role(staff=True)
@require_POST
def staff_transition(request, order_id):
    get_object_or_404(Order, pk=order_id)
    try:
        transition_order(order_id, request.POST.get("status", ""), token=request.POST.get("token"))
    except OrderError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Order #{order_id} updated.")
    return redirect("staff_queue")


@for_role(staff=True)
def staff_menu(request):
    items = MenuItem.objects.order_by("category", "name")
    return render(request, "canteen/staff_menu.html", {"items": items})


@for_role(staff=True)
def staff_menu_form(request, item_id=None):
    item = get_object_or_404(MenuItem, pk=item_id) if item_id else None
    form = MenuItemForm(request.POST if request.method == "POST" else None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Menu item saved.")
        return redirect("staff_menu")
    return render(request, "canteen/staff_form.html", {
        "form": form, "title": "Edit menu item" if item else "Add menu item",
        "back": "staff_menu",
    })


@for_role(staff=True)
@require_POST
def staff_toggle_availability(request, item_id):
    item = get_object_or_404(MenuItem, pk=item_id)
    MenuItem.objects.filter(pk=item.pk).update(available=~F("available"))
    messages.success(request, "Menu availability updated.")
    return redirect("staff_menu")


@for_role(staff=True)
def staff_slots(request):
    slots = PickupSlot.objects.order_by("-start_at")
    return render(request, "canteen/staff_slots.html", {"slots": slots})


@for_role(staff=True)
def staff_slot_form(request, slot_id=None):
    if request.method == "POST":
        with transaction.atomic():
            slot = get_object_or_404(PickupSlot, pk=slot_id) if slot_id else None
            form = PickupSlotForm(request.POST, instance=slot)
            if form.is_valid():
                pickup = form.save(commit=False)
                if slot:
                    pickup.save(update_fields=["start_at", "end_at", "capacity"])
                else:
                    pickup.save()
                messages.success(request, "Pickup window saved.")
                return redirect("staff_slots")
    else:
        slot = get_object_or_404(PickupSlot, pk=slot_id) if slot_id else None
        form = PickupSlotForm(instance=slot)
    return render(request, "canteen/staff_form.html", {
        "form": form, "title": "Edit pickup window" if slot else "Add pickup window",
        "back": "staff_slots",
        "hint": "Reserved pickup windows keep their original times." if slot and slot.reserved_count else "",
    })


@for_role(staff=True)
def staff_reports(request):
    raw_date = request.GET.get("date", "")
    try:
        day = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        day = timezone.localdate()
        messages.error(request, "Choose a valid date.")
    orders = list(Order.objects.filter(slot__start_at__date=day).prefetch_related("items"))
    counts = Counter(order.status for order in orders)
    collected = [order for order in orders if order.status == Order.Status.COLLECTED]
    sales = sum((order.total for order in collected), Decimal("0"))
    popularity = Counter()
    for order in collected:
        for item in order.items.all():
            popularity[item.item_name] += item.quantity
    metrics = [
        {"label": label, "count": counts[value]} for value, label in Order.Status.choices
    ]
    popular = sorted(popularity.items(), key=lambda item: (-item[1], item[0]))
    return render(request, "canteen/staff_reports.html", {
        "day": day, "scheduled": len(orders), "collected": len(collected),
        "sales": sales, "metrics": metrics, "popular": popular,
    })
