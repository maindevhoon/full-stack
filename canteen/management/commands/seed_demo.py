from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from canteen.models import MenuItem, PickupSlot


MENU = [
    ("Paneer Kathi Roll", "Grilled paneer and vegetables in a rolled flatbread.", "meals", "85", True),
    ("Veg Rice Bowl", "Seasoned rice with roasted vegetables and raita.", "meals", "95", True),
    ("Masala Sandwich", "Toasted bread with spiced potato and green chutney.", "snacks", "55", True),
    ("Samosa", "Crisp pastry with a lightly spiced potato filling.", "snacks", "20", True),
    ("Cold Coffee", "Chilled coffee blended with milk.", "drinks", "60", True),
    ("Lemon Iced Tea", "Brewed tea with lemon, served over ice.", "drinks", "45", True),
    ("Chocolate Muffin", "Chocolate sponge with chocolate chips.", "other", "40", False),
]


class Command(BaseCommand):
    help = "Populate a local database with demo accounts, menu items, and upcoming pickup slots."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seeding is available only in local debug mode.")

        with transaction.atomic():
            self.create_account("student_demo", "DemoStudent!2026", "Demo Student", False)
            self.create_account("staff_demo", "DemoStaff!2026", "Canteen Staff", True)

            for name, description, category, price, available in MENU:
                MenuItem.objects.get_or_create(
                    name=name,
                    defaults={
                        "description": description,
                        "category": category,
                        "price": Decimal(price),
                        "available": available,
                    },
                )

            now = timezone.localtime()
            if not PickupSlot.objects.filter(start_at__gt=now).exists():
                first = now.replace(second=0, microsecond=0) + timedelta(minutes=30)
                first += timedelta(minutes=(-first.minute) % 15)
                for i, capacity in enumerate((5, 8, 8, 10)):
                    start = first + timedelta(minutes=15 * i)
                    end = start + timedelta(minutes=15)
                    PickupSlot.objects.update_or_create(
                        start_at=start, defaults={"end_at": end, "capacity": capacity}
                    )

        self.stdout.write(self.style.SUCCESS("Demo accounts, menu, and pickup slots are ready."))

    @staticmethod
    def create_account(username, password, full_name, is_staff):
        users = get_user_model().objects
        account = users.filter(username=username).first()
        if account is None:
            first_name, last_name = full_name.split(" ", 1)
            users.create_user(
                username=username, password=password, first_name=first_name,
                last_name=last_name, is_staff=is_staff,
            )
        elif account.is_staff != is_staff or account.is_superuser or not account.is_active:
            raise CommandError(f"The existing {username} account has an incompatible role.")
