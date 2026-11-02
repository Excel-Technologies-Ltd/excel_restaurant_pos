# Copyright (c) 2026, Excel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, nowdate

TXN = "ArcPOS Loyalty Transaction"
CAMPAIGN = "ArcPOS Loyalty Campaign"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_data(filters)
	return get_columns(), data, None, get_chart(data)


def get_columns():
	return [
		{"label": _("Campaign"), "fieldname": "campaign", "fieldtype": "Link", "options": CAMPAIGN, "width": 130},
		{"label": _("Name"), "fieldname": "campaign_name", "fieldtype": "Data", "width": 180},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Points Issued"), "fieldname": "points", "fieldtype": "Int", "width": 110},
		{"label": _("Budget"), "fieldname": "budget", "fieldtype": "Int", "width": 90},
		{"label": _("Budget Used %"), "fieldname": "budget_used", "fieldtype": "Percent", "width": 110},
		{"label": _("Participants"), "fieldname": "participants", "fieldtype": "Int", "width": 100},
		{"label": _("Orders"), "fieldname": "orders", "fieldtype": "Int", "width": 80},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "width": 120},
		{"label": _("AOV (campaign)"), "fieldname": "aov", "fieldtype": "Currency", "width": 120},
		{"label": _("AOV (other orders)"), "fieldname": "aov_other", "fieldtype": "Currency", "width": 130},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or add_months(nowdate(), -3))
	to_date = getdate(filters.get("to_date") or nowdate())
	campaign_filters = {field: filters.get(field) for field in ("programme", "status") if filters.get(field)}

	rows = []
	campaigns = frappe.get_all(
		CAMPAIGN,
		filters=campaign_filters,
		fields=["name", "campaign_name", "status", "points_budget", "start_datetime", "end_datetime"],
		order_by="start_datetime desc",
	)
	for campaign in campaigns:
		start = max(getdate(campaign.start_datetime), from_date) if campaign.start_datetime else from_date
		end = min(getdate(campaign.end_datetime), to_date) if campaign.end_datetime else to_date
		if start > end:
			continue
		window = {"campaign": campaign.name, "from": f"{start} 00:00:00", "to": f"{end} 23:59:59", "start": start, "end": end}
		stats = frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(points), 0) AS points, COUNT(DISTINCT account) AS participants
			FROM `tab{TXN}`
			WHERE campaign = %(campaign)s AND transaction_type IN ('Earn', 'Bonus', 'Reverse')
				AND posting_datetime BETWEEN %(from)s AND %(to)s
			""",
			window,
			as_dict=True,
		)[0]
		orders = frappe.db.sql(
			f"""
			SELECT COUNT(*) AS orders, COALESCE(SUM(si.base_grand_total), 0) AS revenue
			FROM `tabSales Invoice` si
			WHERE si.docstatus = 1 AND si.name IN (
				SELECT DISTINCT source_name FROM `tab{TXN}`
				WHERE campaign = %(campaign)s AND source_doctype = 'Sales Invoice' AND points > 0
					AND posting_datetime BETWEEN %(from)s AND %(to)s
			)
			""",
			window,
			as_dict=True,
		)[0]
		other = frappe.db.sql(
			f"""
			SELECT AVG(si.base_grand_total)
			FROM `tabSales Invoice` si
			WHERE si.docstatus = 1 AND si.is_return = 0 AND si.posting_date BETWEEN %(start)s AND %(end)s
				AND si.name NOT IN (
					SELECT DISTINCT source_name FROM `tab{TXN}`
					WHERE campaign = %(campaign)s AND source_doctype = 'Sales Invoice'
				)
			""",
			window,
		)[0][0]
		budget = cint(campaign.points_budget)
		order_count = cint(orders.orders)
		rows.append(
			{
				"campaign": campaign.name,
				"campaign_name": campaign.campaign_name,
				"status": campaign.status,
				"points": cint(stats.points),
				"budget": budget or None,
				"budget_used": flt(cint(stats.points) * 100 / budget, 1) if budget else None,
				"participants": cint(stats.participants),
				"orders": order_count,
				"revenue": flt(orders.revenue),
				"aov": flt(orders.revenue) / order_count if order_count else None,
				"aov_other": flt(other) if other else None,
			}
		)
	return rows


def get_chart(data):
	if not data:
		return None
	top = sorted(data, key=lambda r: r["points"], reverse=True)[:15]
	return {
		"data": {
			"labels": [r["campaign_name"] for r in top],
			"datasets": [{"name": _("Points Issued"), "values": [r["points"] for r in top]}],
		},
		"type": "bar",
	}
