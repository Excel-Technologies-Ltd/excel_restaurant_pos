from .tips import tips_api_routes
from .address import address_api_routes
from .feedback import feedback_api_routes
from .item import item_api_routes
from .item_group import item_group_api_routes
from .mode_of_payment import mode_of_payment_api_routes
from .menu import menu_api_routes
from .sales_invoice import sales_invoice_api_routes
from .settings import settings_api_routes
from .territory import territory_api_routes
from .file import file_api_routes
from .table import table_api_routes
from .item_price import item_price_api_routes
from .customer import customer_api_routes
from .report import report_api_routes
from .payments import payments_api_routes
from .meta import meta_api_routes
from .pos_counter import pos_counter_api_routes
from .uber_eats import uber_eats_api_routes
from .payment_entry import payment_entry_api_routes
from .arcpos_offers import arcpos_offers_api_routes
from .pnl_entry import pnl_entry_api_routes

api_routes = {
    **tips_api_routes,
    **address_api_routes,
    **feedback_api_routes,
    **item_api_routes,
    **item_group_api_routes,
    **mode_of_payment_api_routes,
    **menu_api_routes,
    **sales_invoice_api_routes,
    **settings_api_routes,
    **territory_api_routes,
    **file_api_routes,
    **table_api_routes,
    **item_price_api_routes,
    **customer_api_routes,
    **report_api_routes,
    **payments_api_routes,
    **meta_api_routes,
    **pos_counter_api_routes,
    **uber_eats_api_routes,
    **payment_entry_api_routes,
    **arcpos_offers_api_routes,
    **pnl_entry_api_routes,
}
