import pymysql.cursors

import frappe


@frappe.whitelist()
def get_sales_by_service_type(from_date, to_date):
    # Use dedicated connection for procedure call to avoid PyMySQL packet sequence errors
    conn = pymysql.connect(
        **frappe.db.get_connection_settings(),
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.callproc("GetNetSalesByServiceType", (from_date, to_date))
            result = cursor.fetchall()
            # Consume remaining result sets to avoid packet sequence corruption
            while cursor.nextset():
                pass
            return result
    finally:
        conn.close()
