from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from canteen.models import MenuItem, Order, PickupSlot
from canteen.services import place_order, transition_order


class PortalViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user("student", password="Example-Lunch-3003")
        cls.other = User.objects.create_user("other", password="Example-Other-4004")
        cls.staff = User.objects.create_user("counter", password="Example-Counter-5005", is_staff=True)
        cls.item = MenuItem.objects.create(
            name="Idli", category=MenuItem.Category.MEALS, price=Decimal("25.25")
        )
        start = (timezone.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
        cls.slot = PickupSlot.objects.create(
            start_at=start, end_at=start + timedelta(minutes=20), capacity=2
        )

    def test_registration_creates_a_student_account(self):
        response = self.client.post(reverse("register"), {
            "first_name": "Demo",
            "username": "fresh-student",
            "password1": "January-Canteen-775!",
            "password2": "January-Canteen-775!",
            "is_staff": "on",
        })
        self.assertRedirects(response, reverse("menu"))
        user = User.objects.get(username="fresh-student")
        self.assertEqual(user.first_name, "Demo")
        self.assertFalse(user.is_staff)

    def test_order_workflow_with_permissions_and_receipt(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse("menu")), "Idli")
        self.assertEqual(self.client.get(reverse("staff_queue")).status_code, 403)
        response = self.client.post(reverse("add_to_cart", args=[self.item.pk]), {"quantity": 2})
        self.assertRedirects(response, reverse("menu"))
        self.assertContains(self.client.get(reverse("cart")), "₹50.50")
        response = self.client.post(reverse("checkout"), {"slot": self.slot.pk}, follow=True)
        order = Order.objects.get(user=self.student)
        self.assertContains(response, order.token)
        self.assertContains(response, "₹50.50")
        self.assertContains(self.client.get(reverse("order_history")), f"Order #{order.pk}")
        receipt = reverse("order_detail", args=[order.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(receipt).status_code, 404)

        self.client.force_login(self.staff)
        queue = self.client.get(reverse("staff_queue"))
        self.assertContains(queue, "Start preparing")
        self.assertNotContains(queue, order.token)
        change = reverse("staff_transition", args=[order.pk])
        self.client.post(change, {"status": Order.Status.PREPARING})
        self.client.post(change, {"status": Order.Status.READY})
        denied = self.client.post(change, {"status": Order.Status.COLLECTED, "token": "bad"}, follow=True)
        self.assertContains(denied, "does not match")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.READY)
        self.client.post(change, {"status": Order.Status.COLLECTED, "token": order.token})
        self.client.post(change, {"status": Order.Status.COLLECTED, "token": order.token})
        self.client.force_login(self.student)
        self.assertContains(self.client.get(receipt), "Collected")

    def test_no_checkout_when_item_becomes_unavailable(self):
        self.client.force_login(self.student)
        self.client.post(reverse("add_to_cart", args=[self.item.pk]), {"quantity": 1})
        MenuItem.objects.filter(pk=self.item.pk).update(available=False)
        response = self.client.get(reverse("checkout"), follow=True)
        self.assertContains(response, "Remove unavailable items to continue.")
        self.assertFalse(Order.objects.exists())

    def test_staff_report_counts_collected_sales_only(self):
        placed = place_order(self.student, self.slot.pk, {self.item.pk: 1})
        collected = place_order(self.other, self.slot.pk, {self.item.pk: 2})
        for status in (Order.Status.PREPARING, Order.Status.READY, Order.Status.COLLECTED):
            transition_order(collected.pk, status, token=collected.token)
        self.client.force_login(self.staff)
        report = self.client.get(reverse("staff_reports"), {
            "date": timezone.localtime(self.slot.start_at).date().isoformat()
        })
        self.assertEqual(report.context["scheduled"], 2)
        self.assertEqual(report.context["collected"], 1)
        self.assertEqual(report.context["sales"], Decimal("50.50"))
        self.assertEqual(report.context["popular"], [("Idli", 2)])
        placed.refresh_from_db()
        self.assertIsNone(placed.collected_at)

    def test_reserved_window_keeps_times_and_capacity_floor(self):
        place_order(self.student, self.slot.pk, {self.item.pk: 1})
        self.client.force_login(self.staff)
        change_url = reverse("staff_slot_edit", args=[self.slot.pk])
        response = self.client.post(change_url, {"capacity": 0})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        response = self.client.post(change_url, {
            "start_at": "2026-01-01T10:00", "end_at": "2026-01-01T11:00", "capacity": 3,
        })
        self.assertRedirects(response, reverse("staff_slots"))
        slot = PickupSlot.objects.get(pk=self.slot.pk)
        self.assertEqual(slot.start_at, self.slot.start_at)
        self.assertEqual(slot.end_at, self.slot.end_at)
        self.assertEqual(slot.reserved_count, 1)
        self.assertEqual(slot.capacity, 3)

    def test_cart_mutations_require_post_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        url = reverse("add_to_cart", args=[self.item.pk])
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, {"quantity": 2}).status_code, 403)
