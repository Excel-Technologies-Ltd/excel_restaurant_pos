from frappe.utils import get_url, nowdate, add_days
import datetime
import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_category_list():
    query = """
        SELECT name, image
        FROM `tabItem Group`
        WHERE is_restaurant_pos = 1
    """
    return frappe.db.sql(query, as_dict=True)


@frappe.whitelist(allow_guest=True)
def get_food_item_list(category=None):
    # Set default category to "All" if not provided
    if not category:
        category = "All"

    # Determine the categories to query
    if category == "All":
        category_list = (
            get_category_list_with_array()
        )  # Assuming this function returns a list of categories
    else:
        category_list = [category]

    # Fetch items using the Frappe API
    item_list = frappe.get_all(
        "Item",
        filters={
            "item_group": ["in", category_list],  # Filter by category list
            "variant_of": "",  # Exclude variants
        },
        fields=[
            "item_name",
            "item_code",
            "item_group",
            "image",
            "has_variants",
            "description",
            "custom_is_gift_card_item",
            "custom_gift_card_value",
        ],
        order_by="creation",
        limit_page_length=100,  # Adjust this to limit the number of items fetched
    )

    # Separate items with and without variants
    variant_items = [item["item_code"] for item in item_list if item["has_variants"]]
    non_variant_items = [
        item["item_code"] for item in item_list if not item["has_variants"]
    ]

    # Get default variant items in batch for items with variants
    default_variants = frappe.get_all(
        "Item",
        filters={"variant_of": ["in", variant_items], "default_variant": 1},
        fields=["variant_of", "item_code"],
    )
    # Map each parent item to its default variant
    default_variant_map = {
        variant["variant_of"]: variant["item_code"] for variant in default_variants
    }

    # Fetch prices in batch for all items (both default variants and non-variants)
    all_item_codes = non_variant_items + list(default_variant_map.values())
    prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", all_item_codes], "price_list": "Standard Selling"},
        fields=["item_code", "price_list_rate"],
    )
    # Create a dictionary of item prices for quick lookup
    price_map = {price["item_code"]: price["price_list_rate"] for price in prices}

    # Attach price to each item in the list
    for item in item_list:
        if item["has_variants"]:
            # Use default variant price if available
            variant_code = default_variant_map.get(item["item_code"])
            item["price"] = price_map.get(variant_code, 0) if variant_code else 0
        else:
            # Non-variant item price
            item["price"] = price_map.get(item["item_code"], 0)

    return item_list


@frappe.whitelist(allow_guest=True)
def get_single_food_item_details(item_code):
    item_details = frappe.get_doc("Item", item_code)
    item_name = item_details.item_name
    image = item_details.image
    has_variants = bool(item_details.has_variants)
    if has_variants:
        variant_item_list = get_variant_item_list(item_code)
        default_variant = next(
            (
                variant
                for variant in variant_item_list
                if variant.get("default_variant") == True
            ),
            None,
        )
        if default_variant:
            price = default_variant["price"]
        else:
            price = variant_item_list[0]["price"]
    else:
        variant_item_list = []
        price = frappe.db.get_value(
            "Item Price",
            {"item_code": item_code, "price_list": "Standard Selling"},
            "price_list_rate",
        )
    add_ons_item_list = get_add_ons_list(item_code)
    response = {
        "item_code": item_code,
        "item_name": item_name,
        "image": image,
        "has_variants": has_variants,
        "price": price,
        "add_ons_item_list": add_ons_item_list,
        "description": item_details.description,
        "custom_is_gift_card_item": int(item_details.get("custom_is_gift_card_item") or 0),
        "custom_gift_card_value": float(item_details.get("custom_gift_card_value") or 0),
    }
    if has_variants:
        response["variant_item_list"] = variant_item_list
    return response


def get_category_list_with_array():
    category_list = get_category_list()
    return [category["name"] for category in category_list]


def get_add_ons_list(item_code):
    query = """
        SELECT fi.item_id as item_code ,i.item_name as item_name,i.image as image,COALESCE(ip.price_list_rate, 0) as price
        FROM `tabFood Item List` as fi
        LEFT JOIN `tabItem` as i ON fi.item_id = i.item_code
        LEFT JOIN `tabItem Price` as ip ON fi.item_id = ip.item_code and ip.price_list = "Standard Selling"
        WHERE fi.parent = %s and fi.parentfield= "add_ons_item_list" and fi.parenttype= "Item"
    """
    return frappe.db.sql(query, (item_code,), as_dict=True)


def get_variant_item_list(item_code):
    query = """
        SELECT i.default_variant as default_variant,i.item_code as item_code ,i.item_name as item_name,i.image as image,COALESCE(ip.price_list_rate, 0) as price
        FROM `tabItem` as i
        LEFT JOIN `tabItem Price` as ip ON i.item_code = ip.item_code and ip.price_list = "Standard Selling"
        WHERE i.variant_of = %s
    """
    return frappe.db.sql(query, (item_code,), as_dict=True)


@frappe.whitelist(allow_guest=True)
def make_as_ready_item(body):
    try:
        data = frappe.parse_json(body)
        # Fetch the order document using the order_id
        order_doc = frappe.get_doc("Table Order", data["order_id"])

        # Loop through the items in the order
        for item in order_doc.item_list:
            # Check if the item matches the name
            if item.name.lower() == data["item_name"].lower():  # Case-insensitive match
                item.is_ready = 1
                item.order_ready_time = frappe.utils.now_datetime()
                order_doc.save(ignore_permissions=True)  # Save the order document
                frappe.db.commit()  # Commit the transaction
                return {
                    "status": "success",
                }

        # If the item wasn't found, return failure response
        return {
            "status": "failed",
        }

    except Exception as e:
        # Log error and return failure message
        return {"status": "failure", "message": e}


@frappe.whitelist(allow_guest=True)
def make_as_accepted_item(body):
    try:
        data = frappe.parse_json(body)
        # Fetch the order document using the order_id
        order_doc = frappe.get_doc("Table Order", data["order_id"])

        # Loop through the items in the order
        for item in order_doc.item_list:
            # Check if the item matches the name
            if item.name.lower() == data["item_name"].lower():  # Case-insensitive match
                item.is_accepted = 1
                item.order_accepted_time = frappe.utils.now_datetime()
                order_doc.save(ignore_permissions=True)  # Save the order document
                frappe.db.commit()  # Commit the transaction
                return {
                    "status": "success",
                }

        # If the item wasn't found, return failure response
        return {
            "status": "failed",
        }

    except Exception as e:
        # Log error and return failure message
        return {
            "status": "failure",
            "message": "An error occurred while processing your request.",
        }


@frappe.whitelist(allow_guest=True)
def make_as_create_recipe_item(order_id=None, item_name=None):
    if not order_id or not item_name:
        return False
    try:
        order_doc = frappe.get_doc("Table Order", order_id)
        for item in order_doc.item_list:
            if item.item.lower() == item_name.lower():
                item.is_create_recipe = 1
                item.remarks = "Recipe created"
                order_doc.save(ignore_permissions=True)
                frappe.db.commit()
                return True
    except Exception as e:
        print(e)
        return False


@frappe.whitelist(allow_guest=True)
def make_as_unready_recipe_item(
    order_id="Order-11-051", item_name="Beef Burger", remarks="Insufficient ingredients"
):
    try:
        order_doc = frappe.get_doc("Table Order", order_id)
        for item in order_doc.item_list:
            if item.item.lower() == item_name.lower():
                item.is_ready = 0
                order_doc.status = "Work in progress"
                item.remarks = remarks
                order_doc.save()
                frappe.db.commit()
                return f"Product {item_name.lower()} made as unready for order {order_id} {item.item.lower()}"
    except Exception as e:
        print(e)
        return False


@frappe.whitelist(allow_guest=True)  # Makes the endpoint publicly accessible
def create_order(data):
    """
    Public API endpoint to create or update a 'Table Order' in ERPNext.

    :param data: JSON dictionary with required fields to create the order.
    :return: JSON response with success status or error message.
    """
    try:
        # Parse incoming data
        order_data = frappe.parse_json(data)
        settings = frappe.get_doc("Restaurant Settings")

        existing_order_name = ""
        # Check for existing order
        if order_data["table"]:
            existing_order_name = frappe.db.exists(
                "Table Order",
                {
                    "table": order_data["table"],
                    "status": ["not in", ["Completed", "Canceled"]],
                },
            )
        print(existing_order_name)

        if existing_order_name:
            print("working")
            # Fetch the existing order using the name returned by frappe.db.exists()
            order_doc = frappe.get_doc("Table Order", existing_order_name)
            new_items = order_data.get("item_list", [])

            # Add new items to the existing order
            for item in new_items:
                order_doc.append("item_list", item)

            # Update amounts
            order_doc.amount = float(order_doc.amount) + float(
                order_data.get("amount", 0)
            )  # Safely cast to float
            order_doc.total_amount = float(order_doc.total_amount) + float(
                order_data.get("total_amount", 0)
            )  # Safely cast to float
            order_doc.discount = float(order_doc.discount) + float(
                order_data.get("discount", 0)
            )  # Safely cast to float
            order_doc.status = (
                "Work in progress"
                if order_doc.status != "Order Placed"
                else "Order Placed"
            )  # Update order status to work in progress
            order_doc.remarks = order_data.get("remarks")
            if order_data.get("custom_gift_cards_for"):
                order_doc.custom_gift_cards_for = order_data.get("custom_gift_cards_for")

            # Save and commit the changes to the existing order
            order_doc.save(ignore_permissions=True)
            frappe.db.commit()

            return {
                "status": "success",
                "message": "Order updated successfully",
                "order_name": order_doc.name,
            }

        # Mandatory fields check
        required_fields = ["amount", "item_list"]
        for field in required_fields:
            if not order_data.get(field):
                return {
                    "status": "error",
                    "message": _("Field '{0}' is required.").format(field),
                }

        # Create a new 'Table Order' document if no existing order
        order_doc = frappe.get_doc(
            {
                "doctype": "Table Order",
                "customer": order_data.get("customer") or settings.customer,
                "credit_sales": order_data.get("credit_sales") or 0,
                "table": order_data["table"],
                "amount": float(order_data["amount"]),
                "total_amount": float(order_data["total_amount"]) or 0,
                "item_list": order_data["item_list"],
                "floor": order_data.get("floor"),
                "address": order_data.get("address")
                or "Test Address",  # Corrected typo from "adresss"
                "tax": order_data.get("tax") or 0,
                "discount": order_data.get("discount") or 0,
                "discount_type": order_data.get("discount_type"),
                "company": order_data.get("company"),
                "customer_name": order_data.get("customer_name") or "Test User",
                "remarks": order_data.get("remarks"),
                "status": order_data.get("status", "Order Placed"),
                "docstatus": 1 if order_data.get("status") == "Completed" else 0,
                "is_paid": 1 if order_data.get("is_paid") else 0,
                "custom_gift_cards_for": order_data.get("custom_gift_cards_for") or "",
                # Default to "Order Placed"
            }
        )

        # Insert the document into the database
        order_doc.insert(ignore_permissions=True)

        # Commit the transaction
        frappe.db.commit()

        return {
            "status": "success",
            "message": "Order created successfully",
            "order_name": order_doc.name,
        }

    except frappe.ValidationError as e:
        print("validation error")
        print(e)
        frappe.log_error("Order Creation Error", str(e))
        return {"status": "error", "message": str(e)}

    except Exception as e:
        print("exce")
        print(e)
        frappe.log_error("Unknown Error in Order Creation", str(e))
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_running_order_list():
    order_list = frappe.get_all(
        "Table Order",
        fields=["*"],
        filters=[["status", "!=", "Completed"], ["status", "!=", "Canceled"]],
        order_by="creation desc",
    )
    for order in order_list:
        order["item_list"] = get_order_item_list(order.name)
    return order_list


@frappe.whitelist(allow_guest=True)
def get_running_order_item_list(table_id):
    print("table_id", table_id)
    if not table_id:
        return []
    order_list = frappe.get_all(
        "Table Order",
        fields=["*"],
        filters=[
            ["status", "!=", "Completed"],
            ["status", "!=", "Canceled"],
            ["table", "=", table_id],
        ],
        order_by="creation desc",
    )
    for order in order_list:
        order["item_list"] = get_order_item_list(order.name)
    if len(order_list) > 0:
        return order_list[0].item_list
    else:
        return []


@frappe.whitelist(allow_guest=True)
def get_tax_rate():
    settings = frappe.get_doc("Restaurant Settings")
    return int(settings.tax_rate) / 100


@frappe.whitelist()
def get_order_list(status=None, page=1, page_size=10):
    try:
        # Calculate offset
        page = int(page) if page else 1
        page_size = int(page_size) if page_size else 10
        start = (page - 1) * page_size

        # Apply filters and fetch data
        filters = [["status", "in", [status]]] if status else []
        order_list = frappe.get_all(
            "Table Order",
            fields=["*"],
            filters=filters,
            order_by="modified desc",
            limit_start=start,
            limit_page_length=page_size,
        )

        # Get total count for pagination metadata
        total_count = frappe.db.count("Table Order", filters=filters)

        # Add item list to each order
        for order in order_list:
            order["item_list"] = get_order_item_list(order.name)

        # Prepare response
        response = {
            "data": order_list,
            "currentPage": page,
            "totalPages": (total_count + page_size - 1)
            // page_size,  # Ceiling division
            "totalDataCount": total_count,
            "itemsPerPage": page_size,
        }
        return response
    except Exception as e:
        frappe.log_error("get_order_list API Error", str(e))
        return {"error": str(e)}


@frappe.whitelist()
def get_chef_order_list(page=1, page_size=10):
    try:
        # Convert page and page_size to integers
        page = int(page) if page else 1
        page_size = int(page_size) if page_size else 10
        start = (page - 1) * page_size

        # Define filters with OR conditions
        or_filters = [
            ["status", "=", "Work in progress"],
            ["status", "=", "Preparing"],
            ["status", "=", "Ready to Serve"],
        ]

        # Fetch the orders with pagination
        order_list = frappe.get_all(
            "Table Order",
            fields=["*"],
            or_filters=or_filters,
            order_by="modified desc",
            limit_start=start,
            limit_page_length=page_size,
        )

        # Get total count for pagination
        total_count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabTable Order`
            WHERE status IN (%s, %s)
        """,
            ("Work in progress", "Ready to Serve"),
        )[0][0]
        # Add item list to each order
        for order in order_list:
            order["item_list"] = get_order_item_list(order.name)

        # Prepare response
        response = {
            "data": order_list,
            "currentPage": page,
            "totalPages": (total_count + page_size - 1)
            // page_size,  # Ceiling division
            "totalDataCount": total_count,
            "itemsPerPage": page_size,
        }
        return response
    except Exception as e:
        frappe.log_error("get_chef_order_list API Error", str(e))
        return {"error": str(e)}


@frappe.whitelist()
def get_order_item_list(order_id):
    return frappe.get_all(
        "Table Order Item",
        filters={"parent": order_id},
        fields=[
            "item",
            "qty",
            "amount",
            "rate",
            "is_parcel",
            "is_ready",
            "name",
            "parent",
            "remarks",
            "is_accepted",
            "is_create_recipe",
            "is_recipe_item",
            "custom_is_gift_card_item",
            "custom_gift_card_type",
            "custom_gift_card_code",
            "custom_gift_amount",
        ],
        order_by="creation desc",
    )


@frappe.whitelist(allow_guest=True)
def get_roles(user):
    roles = frappe.db.sql(
        """
        SELECT `tabHas Role`.`role` AS `Role`
        FROM `tabHas Role`
        JOIN `tabUser` ON `tabUser`.`name` = `tabHas Role`.`parent`
        WHERE `tabUser`.`name` = %(user)s
    """,
        {"user": user},
        as_dict=True,
    )

    return roles


@frappe.whitelist(allow_guest=True)
def check_coupon_code(data):
    coupon_code = frappe.parse_json(data).get("coupon_code")
    if not coupon_code:
        return {"status": "error", "message": "Invalid"}
    try:
        from excel_restaurant_pos.shared.coupon.services import (
            COUPON_STATUS_ACTIVE,
            refresh_coupon_status,
        )

        coupon_name = frappe.db.get_value("Coupon Code", {"coupon_code": coupon_code}, "name")
        if not coupon_name:
            return {"status": "error", "message": "Invalid"}

        coupon = frappe.get_doc("Coupon Code", coupon_name)
        status = refresh_coupon_status(coupon)
        if status != COUPON_STATUS_ACTIVE:
            return {"status": "error", "message": status}

        discount_type = (coupon.custom_discount_type or "").strip().lower()
        if discount_type == "flat amount":
            discount_type = "flat"

        return {
            "status": "success",
            "discount_type": discount_type,
            "amount": coupon.custom_discount_amount,
            "disc_upto_amount": coupon.custom_disc_upto_amount,
        }

    except Exception as e:
        frappe.log_error(f"Error in check_coupon_code: {str(e)}")
        return "An error occurred while checking the coupon code."


@frappe.whitelist(allow_guest=True)
def get_logo_and_title():
    hostname = get_url()
    settings = frappe.get_doc("Restaurant Settings")
    return {"logo": f"{settings.logo}", "title": settings.title}


@frappe.whitelist(allow_guest=True)
def get_last_seven_days_sales():
    """
    Returns a list of dictionaries for the last 7 days (including today) with:
        - posting_date (YYYY-MM-DD)
        - day_name (e.g., Monday, Tuesday)
        - total_sales (grand_total sum for that day, or 0 if no sales)
    """
    today = datetime.date.today()

    # Create a map for each of the last 7 days, defaulting to 0 sales
    daily_sales_map = {}
    for i in range(7):
        day = today - datetime.timedelta(days=i)
        daily_sales_map[day] = 0.0

    # We'll query from 6 days ago up to today (total 7 days, including the present)
    start_date = today - datetime.timedelta(days=6)

    # Fetch actual sales from the database
    query_results = frappe.db.sql(
        """
        SELECT 
            DATE(posting_date) AS posting_date,
            SUM(grand_total) AS total_sales
        FROM `tabPOS Invoice`
        WHERE 
            docstatus = 1
            AND posting_date BETWEEN %s AND %s
        GROUP BY DATE(posting_date)
        ORDER BY posting_date
    """,
        (start_date, today),
        as_dict=True,
    )

    # Update our map with actual totals
    for row in query_results:
        if row.posting_date in daily_sales_map:
            daily_sales_map[row.posting_date] = row.total_sales or 0.0

    # Convert map to a sorted list of dicts
    output = []
    for day in sorted(daily_sales_map.keys()):
        output.append(
            {
                "posting_date": str(day),
                "day_name": day.strftime("%A"),  # E.g. "Saturday", "Sunday", etc.
                "total_sales": daily_sales_map[day],
            }
        )

    return output


@frappe.whitelist(allow_guest=True)
def get_top_items_by_sales_period(period="weekly", item_count=5):
    """
    Fetch the Top N Items (default 5) by total sales amount
    from POS Invoices for a given period ("weekly", "monthly", "yearly", etc.).

    Returns a list of dicts with:
        - item_code
        - total_sales
        - item_name
    """
    # Ensure item_count is an integer
    item_count = int(item_count) if item_count else 5

    start_date = get_start_date_for_period(period)

    # Use f-string for dynamic LIMIT
    query = f"""
        SELECT 
            pii.item_code AS item_code,
            SUM(pii.amount) AS total_sales
        FROM `tabPOS Invoice Item` pii
        JOIN `tabPOS Invoice` pi ON pi.name = pii.parent
        WHERE 
            pi.docstatus = 1
            AND pi.posting_date >= %s
        GROUP BY pii.item_code
        ORDER BY total_sales DESC
        LIMIT {item_count}
    """

    data = frappe.db.sql(query, (start_date,), as_dict=True)

    # Fetch item_name for readability
    for row in data:
        row["item_name"] = (
            frappe.db.get_value("Item", row["item_code"], "item_name")
            or row["item_code"]
        )

    return data


@frappe.whitelist(allow_guest=True)
def get_top_item_groups_by_sales_period(period="weekly", group_count=5):
    """
    Fetch the Top N Item Groups (default 5) by total sales amount
    from POS Invoices for a given period ("weekly", "monthly", "yearly", etc.).

    Returns a list of dicts with:
        - item_group
        - total_sales
    """
    group_count = int(group_count) if group_count else 5

    start_date = get_start_date_for_period(period)

    # Build a query grouped by item_group
    query = f"""
        SELECT 
            i.item_group AS item_group,
            SUM(pii.amount) AS total_sales
        FROM `tabPOS Invoice Item` pii
        JOIN `tabPOS Invoice` pi ON pi.name = pii.parent
        JOIN `tabItem` i ON pii.item_code = i.item_code
        WHERE 
            pi.docstatus = 1
            AND pi.posting_date >= %s
        GROUP BY 
            i.item_group
        ORDER BY 
            total_sales DESC
        LIMIT {group_count}
    """

    data = frappe.db.sql(query, (start_date,), as_dict=True)
    return data


def get_start_date_for_period(period):
    """
    Utility function to calculate start_date based on the 'period' parameter.
    Adjust as needed (e.g., to use start of current month/year instead of X days ago).
    """
    today = nowdate()

    if period == "weekly":
        # Last 7 days
        return add_days(today, -7)

    elif period == "monthly":
        # Option A: Last 30 days
        return add_days(today, -30)

        # Option B (alternate): From start of current month
        # return get_first_day(today)

    elif period == "yearly":
        # Option A: Last 365 days
        return add_days(today, -365)

        # Option B (alternate): From start of current year
        # return get_year_start(today)

    else:
        # Default fallback if unknown period is passed
        return add_days(today, -7)


@frappe.whitelist(allow_guest=True)
def dashboard_data():
    chef_orders_count = frappe.db.sql(
        """
            SELECT COUNT(*)
            FROM `tabTable Order`
            WHERE status IN (%s, %s)
        """,
        ("Work in progress", "Ready to Serve"),
    )[0][0]
    paid_orders_count = frappe.db.count("Table Order", filters={"status": "Completed"})
    canceled_orders_count = frappe.db.count(
        "Table Order", filters={"status": "Canceled"}
    )
    unpaid_orders_count = frappe.db.sql(
        """
            SELECT COUNT(*)
            FROM `tabTable Order`
            WHERE status IN (%s, %s, %s)
        """,
        ("Work in progress", "Ready to Serve", "Order Placed"),
    )[0][0]
    top_monthly_items = get_top_items_by_sales_period(period="monthly", item_count=1)[0]
    top_weekly_items = get_top_items_by_sales_period(period="weekly", item_count=1)[0]
    top_yearly_items = get_top_items_by_sales_period(period="yearly", item_count=1)[0]
    top_monthly_item_groups = get_top_item_groups_by_sales_period(
        period="monthly", group_count=1
    )[0]
    top_weekly_item_groups = get_top_item_groups_by_sales_period(
        period="weekly", group_count=1
    )[0]

    top_yearly_item_groups = get_top_item_groups_by_sales_period(
        period="yearly", group_count=1
    )[0]

    return {
        "chef_orders_count": chef_orders_count,
        "total_orders_count": paid_orders_count,
        "canceled_orders_count": canceled_orders_count,
        "unpaid_orders_count": unpaid_orders_count,
        "top_monthly_item": top_monthly_items.get("item_code"),
        "top_weekly_item": top_weekly_items.get("item_code"),
        "top_yearly_item": top_yearly_items.get("item_code"),
        "top_monthly_category": top_monthly_item_groups.get("item_group"),
        "top_weekly_category": top_weekly_item_groups.get("item_group"),
        "top_yearly_category": top_yearly_item_groups.get("item_group"),
    }
