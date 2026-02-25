from .create_payment import create_payment

__all__ = ["create_payment"]

payment_entry_api_routes = {
    "api.payment_entry.create": "excel_restaurant_pos.api.payment_entry.create_payment",
}
