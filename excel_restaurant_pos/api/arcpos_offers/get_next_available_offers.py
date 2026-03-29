"""Next available ArcPOS Offers by cart / reference amount."""

from collections import defaultdict

import frappe
from frappe.utils import flt, today


@frappe.whitelist(allow_guest=True)
def get_next_available_offers():
    """
    Return the next applicable ArcPOS Offers for a reference amount.

    Tier selection (tiers sorted by ``from_amount`` ascending):

    - Amount below the first tier's ``from_amount``: all offers in the lowest ``(from_amount, to_amount)`` band.
    - Amount in ``[tier[i].from_amount, tier[i+1].from_amount)``: all offers in tiers ``i`` and ``i+1``.
    - Amount at or above the last tier's ``from_amount``: all offers in the last two bands (or the only band).
    Multiple offers sharing the same range are all included when that band matches.

    Request: ``amount`` (required). ``item_section`` (optional): when provided, only offers for that ArcPOS Item Section are returned.
    """
    raw = frappe.form_dict.get("amount")
    if raw is None or raw == "":
        frappe.throw("amount is required")
    amount = flt(raw)

    filters = {"status": "Enabled"}
    item_section = (frappe.form_dict.get("item_section") or "").strip()
    if item_section:
        if not frappe.db.exists("ArcPOS Item Section", item_section):
            frappe.throw(frappe._("Invalid item_section"))
        filters["item_section"] = item_section

    offers = frappe.get_all(
        "ArcPOS Offers",
        filters=filters,
        fields=[
            "name",
            "offer_name",
            "from_amount",
            "to_amount",
            "free_item",
            "starting_date",
            "ending_date",
            "status",
            "item_section",
        ],
        order_by="from_amount asc",
        ignore_permissions=True,
    )

    today_str = today()
    active = []
    for row in offers:
        start = row.get("starting_date")
        end = row.get("ending_date")
        if start and str(start) > today_str:
            continue
        if end and str(end) < today_str:
            continue
        active.append(row)

    if not active:
        return []

    return _select_offers_for_amount(active, amount)


def _group_offers_by_range(rows: list) -> tuple[list[tuple[float, float]], dict]:
    """Group offers by (from_amount, to_amount); return sorted keys and bucket map."""
    buckets: dict[tuple[float, float], list] = defaultdict(list)
    for row in rows:
        key = (
            flt(row.get("from_amount") or 0),
            flt(row.get("to_amount") or 0),
        )
        buckets[key].append(row)
    keys = sorted(buckets.keys(), key=lambda k: (k[0], k[1]))
    return keys, buckets


def _select_offers_for_amount(active: list, amount: float) -> list:
    """
    Pick all offers in each matching tier. Multiple offers sharing the same range
    are all returned when that tier is selected.
    """
    keys, buckets = _group_offers_by_range(active)
    if not keys:
        return []

    amt = flt(amount)
    first_from = keys[0][0]

    if amt < first_from:
        return list(buckets[keys[0]])

    n = len(keys)
    for j in range(n - 1):
        low = keys[j][0]
        nxt_from = keys[j + 1][0]
        if low <= amt < nxt_from:
            return buckets[keys[j]] + buckets[keys[j + 1]]

    if n >= 2:
        return buckets[keys[-2]] + buckets[keys[-1]]
    return list(buckets[keys[-1]])
