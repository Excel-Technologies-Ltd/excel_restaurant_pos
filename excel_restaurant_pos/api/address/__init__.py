"""Address API endpoints."""

from .customer_address import get_customer_address
from .test import test
from .add_customer_address import add_customer_address
from .edit_customer_address import edit_customer_address
from .handlers.add_address_with_link import add_address_with_link
from .handlers.add_contact_with_link import add_contact_with_link

__all__ = [
    "test",
    "get_customer_address",
    "add_customer_address",
    "edit_customer_address",
    "add_address_with_link",
    "add_contact_with_link",
]

address_api_routes = {
    "api.addresses.test": "excel_restaurant_pos.api.address.test",
    "api.addresses.customer": "excel_restaurant_pos.api.address.get_customer_address",
    "api.addresses.add": "excel_restaurant_pos.api.address.add_customer_address",
    "api.addresses.edit": "excel_restaurant_pos.api.address.edit_customer_address",
}
