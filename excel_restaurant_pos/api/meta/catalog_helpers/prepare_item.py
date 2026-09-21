import frappe
from excel_restaurant_pos.shared.item_price import VALIDITY_FIELDS, live_prices


def prepare_item(item_code: str):
    """
    Prepare the item for the catalog API
    """

    # get the item
    item = frappe.get_doc("Item", item_code)
    if not item:
        frappe.throw(f"Item {item_code} not found")

    # prepare item as like meta catalog item
    # Only prices in force today. This published every selling row to Meta
    # regardless of dates, so a scheduled offer was advertised before it began
    # and an expired one after it ended.
    selling_prices = live_prices(
        frappe.get_all(
            "Item Price",
            filters={"item_code": item_code, "selling": 1},
            fields=["price_list", "price_list_rate", *VALIDITY_FIELDS],
        )
    )

    # price map
    price_map = {
        price["price_list"]: f"{price['price_list_rate']} CAD"
        for price in selling_prices
    }

    # catalog item
    description = (
        frappe.utils.strip_html(item.description or "") if item.description else ""
    )
    img_url = frappe.utils.get_url(item.image) if item.image else ""

    # Get standard selling price or default to 0 if not set
    standard_price = price_map.get("Standard Selling", "0 CAD")
    
    catalog_item = {
        "id": item_code,
        "title": item.item_name,
        "description": description,
        "image": [{"url": img_url}],
        "price": standard_price,
        "sale_price": standard_price,
        "availability": "in stock",
        "condition": "new",
        "brand": "BanCan",
        "link": f"https://order.bancankitchen.ca",
    }

    if "Offer Price" in price_map:
        catalog_item["sale_price"] = price_map["Offer Price"]

    return catalog_item
