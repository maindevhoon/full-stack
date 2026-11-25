from django.contrib.auth import views as auth
from django.urls import path

from . import views
from .forms import StudentAuthenticationForm

urlpatterns = [
    path("", views.menu, name="menu"),
    path("accounts/login/", auth.LoginView.as_view(
        template_name="registration/login.html", authentication_form=StudentAuthenticationForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("accounts/logout/", auth.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:item_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:item_id>/", views.update_cart, name="update_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_history, name="order_history"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("staff/", views.staff_queue, name="staff_queue"),
    path("staff/orders/<int:order_id>/transition/", views.staff_transition, name="staff_transition"),
    path("staff/menu/", views.staff_menu, name="staff_menu"),
    path("staff/menu/new/", views.staff_menu_form, name="staff_menu_add"),
    path("staff/menu/<int:item_id>/", views.staff_menu_form, name="staff_menu_edit"),
    path("staff/menu/<int:item_id>/availability/", views.staff_toggle_availability, name="staff_toggle_availability"),
    path("staff/slots/", views.staff_slots, name="staff_slots"),
    path("staff/slots/new/", views.staff_slot_form, name="staff_slot_add"),
    path("staff/slots/<int:slot_id>/", views.staff_slot_form, name="staff_slot_edit"),
    path("staff/reports/", views.staff_reports, name="staff_reports"),
]
