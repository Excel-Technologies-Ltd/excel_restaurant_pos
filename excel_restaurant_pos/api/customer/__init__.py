"""Customer API endpoints."""

from .create_customer import create_customer
from .update_customer import update_customer

__all__ = [
    "create_customer",
    "update_customer",
]

customer_api_routes = {
    "api.customers.create": "excel_restaurant_pos.api.customer.create_customer",
    "api.customers.update": "excel_restaurant_pos.api.customer.update_customer",
}
