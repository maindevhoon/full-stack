from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import MenuItem, PickupSlot
from .services import MAX_ITEM_QUANTITY

MAX_QUANTITY = MAX_ITEM_QUANTITY


class BootstrapFields:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class StudentRegistrationForm(BootstrapFields, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "username")
        labels = {"first_name": "First name"}


class StudentAuthenticationForm(BootstrapFields, AuthenticationForm):
    pass


class OrderQuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=0, max_value=MAX_QUANTITY)


class AvailableSlotField(forms.ModelChoiceField):
    def label_from_instance(self, slot):
        start = timezone.localtime(slot.start_at)
        end = timezone.localtime(slot.end_at)
        return f"{start:%a, %d %b · %I:%M %p} to {end:%I:%M %p} ({slot.remaining} left)"


class CheckoutForm(BootstrapFields, forms.Form):
    slot = AvailableSlotField(queryset=PickupSlot.objects.none(), empty_label="Choose a pickup window")

    def __init__(self, *args, slots, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slot"].queryset = slots


class MenuItemForm(BootstrapFields, forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ("name", "description", "category", "price", "available")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"price": "Price (₹)", "available": "Available to order"}


class PickupSlotForm(BootstrapFields, forms.ModelForm):
    class Meta:
        model = PickupSlot
        fields = ("start_at", "end_at", "capacity")
        widgets = {
            "start_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "end_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }
        labels = {"start_at": "Starts", "end_at": "Ends", "capacity": "Order limit"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("start_at", "end_at"):
            self.fields[field].input_formats = ["%Y-%m-%dT%H:%M"]
            self.fields[field].disabled = bool(self.instance.reserved_count)

    def clean(self):
        values = super().clean()
        start = values.get("start_at")
        end = values.get("end_at")
        capacity = values.get("capacity")
        if end and start and end <= start:
            self.add_error("end_at", "The end must be after the start.")
        if start and not self.instance.pk and start <= timezone.now():
            self.add_error("start_at", "Choose a future start time.")
        if capacity is not None and capacity < self.instance.reserved_count:
            self.add_error("capacity", "Capacity cannot be below the number of reserved orders.")
        return values
