# Order Receipt PDF — Public API

Download a Sales Invoice as a PDF from the Order Web, rendered with the print
format the restaurant configured.

**Route:** `api.print.invoice_pdf` — `GET` or `POST`, guest reachable.

---

## 1. Which print format is used

The caller does **not** choose. The format is resolved per invoice from
**ArcPOS Settings**:

| Invoice `custom_service_type` | Setting used | Field |
|---|---|---|
| `Delivery` | **Default Delivery Print Format** | `default_delivery_pf` |
| anything else (Pickup, Dine-in, Takeout) | **Default Print Format** | `print_format_for_order` |

If the setting is blank, or points at a Print Format that has since been renamed
or deleted, the render falls back to Frappe's `Standard` format and the mismatch
is written to the error log. A customer downloading their own receipt is never
blocked by a setting nobody filled in.

The format that actually rendered comes back in the **`X-Print-Format`** response
header, so a mis-set setting is visible from the response rather than only from
the PDF.

---

## 2. Calling it

Because it is a plain `GET` with no header requirement, the browser can be sent
straight at it — no ticket, no bearer token, no Frappe session:

```ts
window.location =
  `${API}/api/method/api.print.invoice_pdf?invoice_name=${encodeURIComponent(invoiceName)}`;
```

To keep the backend origin out of the address bar, fetch it and save the blob
from your own origin instead:

```ts
const res = await fetch(
  `${API}/api/method/api.print.invoice_pdf?invoice_name=${encodeURIComponent(invoiceName)}`,
);
if (!res.ok) throw await toApiError(res);

const blob = await res.blob();
const href = URL.createObjectURL(blob);
Object.assign(document.createElement("a"), { href, download: `${invoiceName}.pdf` }).click();
URL.revokeObjectURL(href);
```

`invoice_number`, `sales_invoice` and `name` are accepted as aliases for
`invoice_name`.

### Response

| | |
|---|---|
| `Content-Type` | `application/pdf` |
| `Content-Disposition` | `attachment; filename=ORD-26-01409.pdf` |
| `Content-Length` | exact size |
| `X-Print-Format` | the format that rendered it |
| `Cache-Control` | `no-store, no-cache, must-revalidate, private` |

`Content-Disposition`, `Content-Length` and `X-Print-Format` are readable
cross-origin — Frappe sets `Allow-Origin` but never `Expose-Headers`, so the
route sets it itself.

---

## 3. Errors

| Message | Cause |
|---|---|
| `Invoice name is required` | no `invoice_name` in the request |
| `Invoice {name} not found` | no such Sales Invoice |
| `Order {name} was cancelled.` | the invoice is cancelled (`docstatus = 2`) |
| `Too many requests. Please try again later.` | more than **30 renders per caller per minute** |
| `Could not produce the PDF for order {name}. Please try again.` | the renderer failed — the real `wkhtmltopdf` stderr is in the error log, not in the response |

That last one is worth knowing about: `wkhtmltopdf` fetches any asset a print
format references by absolute URL (logo, QR, stylesheet). If it cannot reach the
site host it fails with `HostNotFoundError`, and **every** PDF for that format
fails. Check the error log before suspecting the invoice.

---

## 4. A caveat worth reading

This route is guest reachable, which matches the existing public order API:
`api.sales_invoices.get` is already `allow_guest` and returns the **entire**
Sales Invoice for any name given to it. The PDF therefore exposes nothing that
is not already exposed.

Both share the same weakness. Order names are sequential (`ORD-26-01409`), so
anyone can walk the range and read other customers' orders — name, address,
phone, items. Closing that means binding access to something the customer knows
and an attacker does not (a token minted at checkout, or a match on the order's
email/phone), and it has to be done for `api.sales_invoices.get` at the same
time or it achieves nothing.
