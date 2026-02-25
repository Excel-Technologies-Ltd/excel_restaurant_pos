import frappe


def execute():
    # We drop the function first to ensure updates are applied during migration
    frappe.db.sql("DROP FUNCTION IF EXISTS `get_Sales Summary` ")

    sql_query = """
    CREATE FUNCTION `get_Sales Summary`(p_from_date DATE,
        p_to_date   DATE
    ) RETURNS longtext CHARSET utf8mb4 COLLATE utf8mb4_bin
        DETERMINISTIC
    BEGIN
        DECLARE v_net_sales          DECIMAL(18,2);
        DECLARE v_discounts          DECIMAL(18,2);
        DECLARE v_discounts_invoice  INT;
        DECLARE v_taxes              DECIMAL(18,2);
        DECLARE v_tips               DECIMAL(18,2);
        DECLARE v_gross_sales        DECIMAL(18,2);
        DECLARE v_amount_collected   DECIMAL(18,2);

        /* Invoice-level aggregation */
        SELECT 
            SUM(COALESCE(net_total, 0)), 
            SUM(COALESCE(discount_amount, 0)), 
            COUNT(DISTINCT CASE WHEN discount_amount > 0 THEN name END)
        INTO 
            v_net_sales, 
            v_discounts, 
            v_discounts_invoice
        FROM 
            `tabSales Invoice`
        WHERE 
            docstatus = 1 
            AND posting_date >= p_from_date 
            AND posting_date <  p_to_date;

        /* Tax & Tip aggregation */
        SELECT 
            SUM(CASE WHEN TSTC.custom_is_tax = 1 OR TSTC.custom_is_delivery_charge = 1 OR TSTC.custom_is_service_charge = 1 THEN TSTC.tax_amount ELSE 0 END),
            SUM(CASE WHEN TSTC.custom_is_tip = 1 THEN TSTC.tax_amount ELSE 0 END)
        INTO 
            v_taxes, 
            v_tips
        FROM 
            `tabSales Taxes and Charges` TSTC
        INNER JOIN 
            `tabSales Invoice` TI ON TI.name = TSTC.parent
        WHERE 
            TI.docstatus = 1 
            AND TI.posting_date >= p_from_date 
            AND TI.posting_date <  p_to_date;

        /* Amount Collected */
        SELECT 
            SUM(COALESCE(credit, 0))
        INTO 
            v_amount_collected
        FROM 
            `tabGL Entry`
        WHERE 
            debit = 0 
            AND is_cancelled = 0 
            AND account LIKE '%%Accounts Receivable%%'
            AND posting_date >= p_from_date 
            AND posting_date <  p_to_date;

        /* Gross Sales */
        SET v_gross_sales = v_net_sales + v_discounts;

        /* JSON Output */
        RETURN JSON_OBJECT(
            'NetSales', v_net_sales,
            'Discounts', v_discounts,
            'DiscountedInvoices', v_discounts_invoice,
            'Taxes', v_taxes,
            'Tips', v_tips,
            'GrossSales', v_gross_sales,
            'AmountCollected', v_amount_collected
        );
    END
    """
    frappe.db.sql(sql_query)
