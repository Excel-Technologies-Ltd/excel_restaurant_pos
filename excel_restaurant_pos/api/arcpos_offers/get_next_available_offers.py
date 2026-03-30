"""Next available ArcPOS Offers by cart / reference amount."""

from collections import defaultdict

import frappe
from frappe.utils import flt, today


@frappe.whitelist(allow_guest=True)
def get_next_available_offers():
    """
    Return the next applicable ArcPOS Offers for a reference amount.

    Tier selection (distinct ``(from_amount, to_amount)`` bands, sorted by ``from_amount``):

    - Amount below the first band's ``from_amount``: only the lowest band.
    - Amount inside a band ``[from, to]``: that band plus the **next** band (never the previous).
    - Amount in a gap between bands: the next band upward plus the one after it (if any).
    - Amount above the last band's ``to_amount``: only the last band.
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
            "item_type",
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
    Return offers for the band that matches ``amount`` plus the next band only
    (never the previous band).
    """
    keys, buckets = _group_offers_by_range(active)
    if not keys:
        return []

    amt = flt(amount)
    n = len(keys)

    if amt < keys[0][0]:
        return list(buckets[keys[0]])

    def _band_plus_next(i: int) -> list:
        out = list(buckets[keys[i]])
        if i + 1 < n:
            out += buckets[keys[i + 1]]
        return out

    for i, (f, t) in enumerate(keys):
        if f <= amt <= t:
            return _band_plus_next(i)

    if amt > keys[-1][1]:
        return list(buckets[keys[-1]])

    for i in range(n - 1):
        lo_to = keys[i][1]
        hi_from = keys[i + 1][0]
        if lo_to < amt < hi_from:
            return _band_plus_next(i + 1)

    return list(buckets[keys[-1]])
