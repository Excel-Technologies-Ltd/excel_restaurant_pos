# Coupon status vs. the order that generated it

`Coupon Code.custom_generated_on_order` links a coupon back to the Sales Invoice
that produced it. That invoice can still be submitted or cancelled afterwards, so
two fields track what happened to it.

| Field | Type | Meaning |
|-------|------|---------|
| `custom_generated_on_order` | Link → Sales Invoice | The order the coupon came from |
| `custom_order_status` | Float | Mirrors that invoice's `docstatus` |
| `custom_status` | Select | The coupon's own lifecycle |

## Transitions

| Invoice event | `custom_order_status` | `custom_status` |
|---------------|----------------------|-----------------|
| Draft (as created) | `0` | untouched |
| **Submitted** | `1` | untouched |
| **Cancelled** | `2` | **`Rejected`** |

A cancelled order means the coupon was never really earned, so it must stop being
spendable. `Rejected` is terminal in `refresh_coupon_status` — neither the nightly
expiry pass nor a later validation can quietly move it back to `Active`, so a
coupon from a voided order stays dead.

Submitting does **not** touch `custom_status`. A coupon is created `Active` (or
`Inactive` for gift card stock), and whether it is `Active` / `Used` / `Expired`
is derived from validity and usage, not from the order.

## Where it runs

Registered on Sales Invoice in `doc_event/__init__.py`:

```python
"on_submit": [ ..., "excel_restaurant_pos.shared.coupon.order_status.on_submit_sales_invoice_coupon_status" ],
"on_cancel": [ "excel_restaurant_pos.shared.coupon.order_status.on_cancel_sales_invoice_coupon_status" ],
```

The submit entry is **last** in `on_submit` on purpose:
`finalize_auto_generated_coupon` and `finalize_gift_card_links` write
`custom_generated_on_order` during that same event (it is deferred from
`before_submit`, where the invoice does not exist yet and the link would fail
validation). Running earlier would find no coupons to update.

Both write with `frappe.db.set_value`, not a full save: the Coupon Code
`on_update` hook regenerates codes, barcodes and QR images, none of which has
anything to do with the order status. Coupons already holding the right values
are skipped, so a resubmit writes nothing.

## Existing data

`excel_restaurant_pos.patches.v1_7_0.backfill_coupon_order_status` aligns coupons
created before these hooks existed, reading the real docstatus of each linked
invoice and rejecting any whose order has since been cancelled. Coupons whose
invoice has been deleted outright are left alone rather than guessed at.

To re-run it:

```bash
bench --site <site> execute \
  excel_restaurant_pos.patches.v1_7_0.backfill_coupon_order_status.execute
```
