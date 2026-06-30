from .api import api_routes
from .overrides import override_item_doctype
from .doc_event import custom_doc_events

# from .doc_event.sales_invoice import sales_invoice_doc_events

# app information
app_name = "excel_restaurant_pos"
app_title = "Excel Restaurant Pos"
app_publisher = "Sohanur Rahman"
app_description = "Restaurant Order and Billing Management System"
app_email = "sohan.dev@excelbd.com"
app_license = "MIT"


# Includes in <head>
# ------------------

# fixtures = [ "Custom Field", "Property Setter", "Role" ]

fixtures = [
    {
        "dt": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "Restaurant Waiter",
                    "Restaurant Manager",
                    "Restaurant Chef",
                    "Restaurant Cashier",
                    "Restro Kitchen Staff",
                    "ArcPOS Manager",
                    "Bartender",
                    "ArcPOS Deny",
                    "Delivery Staff",
                    "ArcPOS Stock User",
                    "ArcPOS Transfer Creator",
                    "ArcPOS Transfer Approver",
                    "ArcPOS PCM Creator",
                    "ArcPOS PCM Approver",
                    "ArcPOS Recipe User",
                    "ArcPOS Recipe Approver",
                    "ArcPOS Register User",
                    "ArcPOS Pickup User",
                    "ArcPOS Delivery User",
                    "ArcPOS Channel User",
                    "ArcPOS Reservation User"
                ],
            ]
        ],
    },
    {"dt": "Custom Field"},
    {"dt": "Property Setter"},
]

# Required Apps with version constraints
# required_apps = ["erpnext"]

# include js, css files in header of desk.html
# app_include_css = "/assets/excel_restaurant_pos/css/excel_restaurant_pos.css"
# app_include_js = "/assets/excel_restaurant_pos/js/excel_restaurant_pos.js"

# include js, css files in header of web template
# web_include_css = "/assets/excel_restaurant_pos/css/excel_restaurant_pos.css"
# web_include_js = "/assets/excel_restaurant_pos/js/excel_restaurant_pos.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "excel_restaurant_pos/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"Sales Invoice": "public/js/sales_invoice.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "excel_restaurant_pos.utils.jinja_methods",
# 	"filters": "excel_restaurant_pos.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "excel_restaurant_pos.install.before_install"
# after_install = "excel_restaurant_pos.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "excel_restaurant_pos.uninstall.before_uninstall"
# after_uninstall = "excel_restaurant_pos.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "excel_restaurant_pos.utils.before_app_install"
# after_app_install = "excel_restaurant_pos.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "excel_restaurant_pos.utils.before_app_uninstall"
# after_app_uninstall = "excel_restaurant_pos.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "excel_restaurant_pos.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes


override_doctype_class = {"ToDo": "excel_restaurant_pos.overrides.todo.ToDo"}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    **custom_doc_events,
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "excel_restaurant_pos.utils.jwt_auth.cleanup_expired_blacklist",
        "excel_restaurant_pos.utils.scheduled_tasks.expire_coupon_codes",
    ],
    "cron": {
        # Sync Clover payments daily at 12:05 AM
        "*/5 * * * *": [
            "excel_restaurant_pos.api.clover.clover_sync.sync_clover_payments",
        ],
        # Delete marked-as-deleted draft invoices and complete past reservations at 1 AM daily
        "0 1 * * *": [
            "excel_restaurant_pos.utils.scheduled_tasks.delete_marked_invoices",
            "excel_restaurant_pos.utils.scheduled_tasks.complete_past_reservations",
        ],
        # Delete stale website orders every 20 minutes
        "*/20 * * * *": [
            "excel_restaurant_pos.utils.scheduled_tasks.delete_stale_website_orders"
        ],
        # Check scheduled orders and send 30-min notifications every 5 minutes
        "*/5 * * * *": [
            "excel_restaurant_pos.utils.scheduled_tasks.check_scheduled_order_notifications"
        ],
        # Send pending delivery/pickup notifications at exact scheduled time every minute
        "* * * * *": [
            "excel_restaurant_pos.utils.scheduled_tasks.check_pending_delivery_notifications"
        ],
        # Send 24-hour reminder emails for table reservations every hour
        # Auto-cancel submitted invoices with Rejected order status every hour
        "0 * * * *": [
            "excel_restaurant_pos.utils.scheduled_tasks.send_reservation_reminders",
            "excel_restaurant_pos.utils.scheduled_tasks.auto_cancel_rejected_invoices",
        ],
    },
}

# Testing
# -------

# before_tests = "excel_restaurant_pos.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "excel_restaurant_pos.event.get_events"
# }

# override doctype class
override_doctype_class = {**override_item_doctype}


override_whitelisted_methods = {
    # territory api routes
    **api_routes,
    # core method override
    "frappe.core.doctype.user.user.sign_up": "excel_restaurant_pos.overrides.user.sign_up",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "excel_restaurant_pos.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["excel_restaurant_pos.utils.before_request"]
# after_request = ["excel_restaurant_pos.utils.after_request"]

# Job Events
# ----------
# before_job = ["excel_restaurant_pos.utils.before_job"]
# after_job = ["excel_restaurant_pos.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

auth_hooks = ["excel_restaurant_pos.auth.validate"]

website_route_rules = [{'from_route': '/frappe-types/<path:app_path>', 'to_route': 'frappe-types'}, {'from_route': '/restaurant/<path:app_path>', 'to_route': 'restaurant'},]
