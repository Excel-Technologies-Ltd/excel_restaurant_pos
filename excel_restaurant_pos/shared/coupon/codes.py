"""QR code and barcode generation for Coupon Code documents.

Both codes encode the coupon_code itself and are stored as attached PNGs so
they are available from desk and from /api/resource list queries.
"""

import io

import frappe
import qrcode

from frappe.utils.file_manager import save_file

QR_FIELD = "custom_qr_code"
BARCODE_FIELD = "custom_barcode"


def build_qr_png(data: str) -> bytes:
    """Render the given text as a PNG QR code."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=20,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def build_barcode_png(data: str) -> bytes:
    """Render the given text as a Code 128 PNG barcode.

    Code 128 because coupon codes are variable length alphanumeric, which the
    numeric fixed-length symbologies (EAN/UPC) cannot encode.

    python-barcode is imported here rather than at module scope: this package is
    imported by the invoice coupon hooks, so a top-level import would turn a
    missing dependency into a failure to submit invoices instead of a coupon
    with no barcode, which the callers already log and tolerate.
    """
    import barcode
    from barcode.writer import ImageWriter

    buffer = io.BytesIO()
    barcode.get("code128", data, writer=ImageWriter()).write(buffer)
    return buffer.getvalue()


# code field -> (filename suffix, renderer)
CODE_BUILDERS = {
    QR_FIELD: ("QRCode", build_qr_png),
    BARCODE_FIELD: ("Barcode", build_barcode_png),
}


def delete_existing_code_files(coupon_name: str, field: str):
    """Remove code files previously attached to this coupon for this field."""
    stale_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Coupon Code",
            "attached_to_name": coupon_name,
            "attached_to_field": field,
        },
        pluck="name",
    )
    for file_name in stale_files:
        frappe.delete_doc(
            "File",
            file_name,
            ignore_permissions=True,
            force=True,
            delete_permanently=True,
        )


def generate_coupon_code_image(coupon_doc, field: str, force: bool = False) -> str | None:
    """Attach a PNG for the given code field and return its file URL."""
    code = (coupon_doc.get("coupon_code") or "").strip()
    if not code:
        return None

    if coupon_doc.get(field) and not force:
        return coupon_doc.get(field)

    suffix, builder = CODE_BUILDERS[field]
    delete_existing_code_files(coupon_doc.name, field)

    file_doc = save_file(
        f"{coupon_doc.name}_{suffix}.png",
        builder(code),
        "Coupon Code",
        coupon_doc.name,
        df=field,
        is_private=0,
    )

    # set_value because on_update fires after the row is written; assigning to the
    # doc alone would not persist. Also lets the backfill run without a save.
    frappe.db.set_value(
        "Coupon Code", coupon_doc.name, field, file_doc.file_url, update_modified=False
    )
    coupon_doc.set(field, file_doc.file_url)
    return file_doc.file_url


def generate_coupon_qr_code(coupon_doc, force: bool = False) -> str | None:
    """Attach the QR code PNG encoding the coupon code."""
    return generate_coupon_code_image(coupon_doc, QR_FIELD, force=force)


def generate_coupon_barcode(coupon_doc, force: bool = False) -> str | None:
    """Attach the Code 128 barcode PNG encoding the coupon code."""
    return generate_coupon_code_image(coupon_doc, BARCODE_FIELD, force=force)


def backfill_coupon_codes():
    """Generate QR codes and barcodes for coupons that predate those fields.

    Wired to ``after_migrate`` because fixtures (which create the fields) sync
    after patches run, so a patch could not rely on the columns.
    Idempotent: only coupons missing a code are touched.
    """
    for field in CODE_BUILDERS:
        if not frappe.db.has_column("Coupon Code", field):
            continue

        pending = frappe.get_all(
            "Coupon Code",
            filters={field: ["in", ["", None]]},
            pluck="name",
        )
        if not pending:
            continue

        for name in pending:
            try:
                generate_coupon_code_image(frappe.get_doc("Coupon Code", name), field)
            except Exception:
                frappe.log_error(
                    title="Coupon Code Image Backfill Failed",
                    message=f"Coupon Code: {name} Field: {field}\n{frappe.get_traceback()}",
                )

        frappe.db.commit()


def ensure_coupon_codes(doc, method=None):
    """Doc event: give every coupon a QR code and a barcode.

    ``coupon_code`` is ``set_only_once`` on the doctype, so it can never change
    after insert. That means a code only ever needs generating when missing --
    there is no code-change case to keep in sync.
    """
    for field in CODE_BUILDERS:
        if doc.get(field):
            continue

        try:
            generate_coupon_code_image(doc, field)
        except Exception:
            # Never block coupon creation because an image could not be rendered.
            frappe.log_error(
                title="Coupon Code Image Generation Failed",
                message=f"Coupon Code: {doc.name} Field: {field}\n{frappe.get_traceback()}",
            )
