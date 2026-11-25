from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from canteen.models import MenuItem, Order, PickupSlot
from canteen.services import OrderError, place_order, transition_order


def order_fixture(capacity=2):
    user = get_user_model().objects.create_user(username="student")
    item = MenuItem.objects.create(name="Tea", price=Decimal("30.75"))
    start = timezone.now() + timedelta(hours=1)
    slot = PickupSlot.objects.create(
        start_at=start, end_at=start + timedelta(minutes=15), capacity=capacity
    )
    return user, item, slot


class OrderServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, cls.item, cls.slot = order_fixture()

    def place(self, quantity=1):
        return place_order(self.user, self.slot.pk, {self.item.pk: quantity})

    def test_total_and_line_details_snapshot_price_at_checkout(self):
        snack = MenuItem.objects.create(name="Snack", price=Decimal("12.10"))
        order = place_order(self.user, self.slot.pk, {self.item.pk: 3, snack.pk: 2})
        self.assertEqual(order.total, Decimal("116.45"))
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.Status.PLACED)
        self.assertTrue(order.token.startswith("CP-"))
        self.assertEqual(order.items.count(), 2)

        self.item.price = Decimal("33.00")
        self.item.name = "Fresh Tea"
        self.item.save(update_fields=["price", "name"])
        line = order.items.get(menu_item=self.item)
        self.assertEqual(line.unit_price, Decimal("30.75"))
        self.assertEqual(line.item_name, "Tea")
        self.assertEqual(line.line_total, Decimal("92.25"))

    def test_unavailable_item_rolls_back_slot_reservation(self):
        self.item.available = False
        self.item.save(update_fields=["available"])
        with self.assertRaisesMessage(OrderError, "no longer available"):
            self.place()
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, 0)
        self.assertFalse(Order.objects.exists())

    def test_missing_item_rolls_back_slot_reservation(self):
        with self.assertRaisesMessage(OrderError, "no longer available"):
            place_order(self.user, self.slot.pk, {self.item.pk + 10: 1})
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, 0)

    def test_rejects_full_slot_and_tokens_are_distinct(self):
        first, second = self.place(), self.place()
        self.assertNotEqual(first.token, second.token)
        with self.assertRaisesMessage(OrderError, "full"):
            self.place()
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, self.slot.capacity)
        self.assertEqual(Order.objects.count(), 2)

    def test_rejects_started_slot(self):
        self.slot.start_at = timezone.now() - timedelta(seconds=30)
        self.slot.save(update_fields=["start_at"])
        with self.assertRaisesMessage(OrderError, "already started"):
            self.place()
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, 0)

    def test_quantity_validation_prevents_reservation(self):
        for quantity in (0, -1, 21, True, "2"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(OrderError):
                    self.place(quantity)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, 0)

    def test_rejects_skipped_states_and_requires_matching_token(self):
        order = self.place()
        with self.assertRaisesMessage(OrderError, "Orders must move"):
            transition_order(order.pk, Order.Status.READY)
        transition_order(order.pk, Order.Status.PREPARING)
        transition_order(order.pk, Order.Status.READY)
        for token in (None, "CP-BAD", "☕"):
            with self.subTest(token=token):
                with self.assertRaisesMessage(OrderError, "does not match"):
                    transition_order(order.pk, Order.Status.COLLECTED, token)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.READY)
        self.assertIsNone(order.collected_at)

    def test_collects_once_with_valid_token(self):
        order = self.place()
        transition_order(order.pk, Order.Status.PREPARING)
        transition_order(order.pk, Order.Status.READY)
        collected = transition_order(order.pk, Order.Status.COLLECTED, f" {order.token.lower()} ")
        self.assertEqual(collected.status, Order.Status.COLLECTED)
        self.assertIsNotNone(collected.collected_at)
        with self.assertRaisesMessage(OrderError, "already been collected"):
            transition_order(order.pk, Order.Status.COLLECTED, order.token)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.reserved_count, 1)


class ConcurrentOrderTests(TransactionTestCase):
    def test_two_students_compete_for_one_slot_without_overbooking(self):
        student, item, slot = order_fixture(capacity=1)
        other_student = get_user_model().objects.create_user(username="other")
        gate = Barrier(2, timeout=10)

        def attempt(user):
            close_old_connections()
            try:
                gate.wait()
                return place_order(user, slot.pk, {item.pk: 1}).pk
            except OrderError as error:
                return str(error)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(attempt, student)
            second = pool.submit(attempt, other_student)
            results = (first.result(timeout=20), second.result(timeout=20))

        confirmations = [result for result in results if isinstance(result, int)]
        rejections = [result for result in results if isinstance(result, str)]
        self.assertEqual(len(confirmations), 1)
        self.assertEqual(len(rejections), 1)
        self.assertIn("full", rejections[0])
        slot.refresh_from_db()
        self.assertEqual(slot.reserved_count, 1)
        self.assertEqual(slot.orders.count(), 1)
