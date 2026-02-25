import frappe


def execute():
    # Drop the procedure first to ensure updates are applied during migration
    frappe.db.sql("DROP PROCEDURE IF EXISTS `GetNetSalesByServiceType`")

    sql_query = """
    CREATE PROCEDURE `GetNetSalesByServiceType`(
        IN p_from_date DATE,
        IN p_to_date DATE
    )
    BEGIN
        SELECT
            custom_service_type,
            SUM(COALESCE(net_total, 0)) AS NetSales,
            ROUND(
                SUM(COALESCE(net_total, 0))
                / SUM(SUM(COALESCE(net_total, 0))) OVER () * 100,
                2
            ) AS Percentage
        FROM
            `tabSales Invoice`
        WHERE
            docstatus = 1
            AND posting_date >= p_from_date
            AND posting_date < p_to_date
        GROUP BY
            custom_service_type;
    END
    """
    frappe.db.sql(sql_query)
