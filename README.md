# Canteen Preorder and Pickup System

A Django prototype for one campus canteen. Students can register, browse the menu, fill a cart, reserve a pickup slot, and track orders by status and token. Staff can manage availability and slot capacity, prepare orders, verify tokens at pickup, and review daily orders and collected sales.

## Setup and demonstration

Follow [readme.txt](readme.txt). Run `python manage.py migrate`, `python manage.py seed_demo`, and `python manage.py runserver` after installing the pinned dependencies in a virtual environment. The local demo accounts and a complete student-to-staff walkthrough are in the same file.

## Project structure

| Path | Contents |
| --- | --- |
| `config/` | Django project settings and URL configuration |
| `canteen/` | Models, order services, forms, views, templates, and static assets |
| `canteen/migrations/` | SQLite schema migrations |
| `canteen/tests/` | Automated tests |
| `submission/` | PBL report |

Checkout validates the selected menu items and reserves capacity as part of order creation. Each order line preserves its quantity, item name, and unit price at purchase. Staff advance orders through **Placed → Preparing → Ready → Collected**. The final step requires the order's pickup token. Payments happen at pickup.

Run `python manage.py test` to verify the application. The daily reports describe recorded orders and collected sales. A canteen user trial and wait-time measurements remain outside the verified results.

Django provides authentication and transactions. Bootstrap provides the responsive layout primitives. [Django transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/) · [Bootstrap](https://getbootstrap.com/docs/5.3/)
