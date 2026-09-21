import frappe
from frappe import _
from frappe.utils import flt, now_datetime


@frappe.whitelist()
def get_expected_cash():
    company = frappe.db.get_single_value("ArcPOS Settings", "company")
    if not company:
        frappe.throw("Default Company is not set in ArcPOS Settings")

    default_cash_account = frappe.db.get_value("Company", company, "default_cash_account")
    if not default_cash_account:
        frappe.throw(f"Default Cash Account is not set for Company {company}")

    expected_cash = frappe.db.sql("""
        SELECT COALESCE(SUM(debit - credit), 0) AS expected_cash
        FROM `tabGL Entry`
        WHERE is_cancelled = 0
        AND account = %s
    """, (default_cash_account,), as_dict=True)
    result = {
      "expected_cash" : expected_cash[0].expected_cash
    }

    return result


@frappe.whitelist()
def submit_clock_in_clock_out():
    submission_type = frappe.form_dict.get("submission_type")
    counter_name = frappe.form_dict.get("counter_name")
    submitted_total = flt(frappe.form_dict.get("submitted_total"))
    reason = frappe.form_dict.get("reason")

    if not submission_type:
        frappe.throw(_("Submission Type is required"))
    if submission_type not in ("Clock In", "Clock Out"):
        frappe.throw(_("Submission Type must be 'Clock In' or 'Clock Out'"))
    if not counter_name:
        frappe.throw(_("Counter Name is required"))

    expected = get_expected_cash()
    expected_cash = flt(expected.get("expected_cash"))

    if expected_cash != submitted_total and not reason:
        frappe.throw(_("Reason is required"))

    doc = frappe.new_doc("Daily Cash Audit")
    doc.submission_type = submission_type
    doc.counter_name = counter_name
    doc.expected_cash = expected_cash
    doc.submitted_total = submitted_total
    doc.reason = reason
    doc.submitted_by = frappe.session.user
    doc.submitted_on = now_datetime()

    # For Clock Out, find and set the Clock In reference
    if submission_type == "Clock Out":
        last_clock_in = frappe.db.get_value(
            "Daily Cash Audit",
            {
                "counter_name": counter_name,
                "submission_type": "Clock In",
                "docstatus": ["in", [0, 1]],
            },
            "name",
            order_by="submitted_on desc",
        )
        if not last_clock_in:
            frappe.throw(_("No Clock In found for counter {0}").format(counter_name))
        doc.clock_in_reference = last_clock_in

    doc.insert(ignore_permissions=True)

    difference = flt(submitted_total) - flt(expected_cash)
    user_roles = [r.role for r in frappe.get_doc("User", frappe.session.user).get("roles")]
    is_manager = "Restaurant Manager" in user_roles

    if flt(difference) == 0 or is_manager:
        doc.submit()
        frappe.db.commit()
    else:
        # Save as draft — only Restaurant Manager can submit from list view
        doc.notify_managers()
        frappe.db.commit()

    doc.reload()
    return doc.as_dict()


@frappe.whitelist()
def check_open_shift():
    counter_name = frappe.form_dict.get("counter_name")
    if not counter_name:
        frappe.throw(_("Counter Name is required"))

    last_clock_in = frappe.db.get_value(
        "Daily Cash Audit",
        {
            "counter_name": counter_name,
            "submission_type": "Clock In",
            "docstatus": ["in", [0, 1]],
        },
        ["name", "submitted_on"],
        order_by="submitted_on desc",
        as_dict=True,
    )

    if not last_clock_in:
        return {"has_open_shift": False}

    has_clock_out = frappe.db.exists(
        "Daily Cash Audit",
        {
            "counter_name": counter_name,
            "submission_type": "Clock Out",
            "docstatus": ["in", [0, 1]],
            "clock_in_reference": last_clock_in.name,
        },
    )

    return {
        "has_open_shift": not has_clock_out,
        "last_clock_in": last_clock_in.name if not has_clock_out else None,
    }


@frappe.whitelist()
def approve_cash_audit():
    audit_name = frappe.form_dict.get("audit_name")
    if not audit_name:
        frappe.throw(_("Audit Name is required"))

    user_roles = [r.role for r in frappe.get_doc("User", frappe.session.user).get("roles")]
    if "Restaurant Manager" not in user_roles:
        frappe.throw(_("Only Restaurant Manager can submit cash audits"))

    doc = frappe.get_doc("Daily Cash Audit", audit_name)
    if doc.docstatus != 0:
        frappe.throw(_("This audit is not in draft state"))

    doc.flags.ignore_permissions = True
    doc.submit()
    frappe.db.commit()

    doc.reload()
    return doc.as_dict()
