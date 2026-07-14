"""QR code generation for Coupon Code documents."""

import io

import frappe
import qrcode

from frappe.utils.file_manager import save_file

QR_FIELD = "custom_qr_code"


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


def delete_existing_qr_files(coupon_name: str):
    """Remove QR files previously attached to this coupon."""
    stale_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Coupon Code",
            "attached_to_name": coupon_name,
            "attached_to_field": QR_FIELD,
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


def generate_coupon_qr_code(coupon_doc, force: bool = False) -> str | None:
    """Attach a QR code PNG encoding the coupon code and return its file URL."""
    code = (coupon_doc.get("coupon_code") or "").strip()
    if not code:
        return None

    if coupon_doc.get(QR_FIELD) and not force:
        return coupon_doc.get(QR_FIELD)

    delete_existing_qr_files(coupon_doc.name)

    file_doc = save_file(
        f"{coupon_doc.name}_QRCode.png",
        build_qr_png(code),
        "Coupon Code",
        coupon_doc.name,
        df=QR_FIELD,
        is_private=0,
    )

    # set_value because on_update fires after the row is written; assigning to the
    # doc alone would not persist. Also lets the backfill run without a save.
    frappe.db.set_value(
        "Coupon Code", coupon_doc.name, QR_FIELD, file_doc.file_url, update_modified=False
    )
    coupon_doc.set(QR_FIELD, file_doc.file_url)
    return file_doc.file_url


def backfill_coupon_qr_codes():
    """Generate QR codes for coupons that predate the QR field.

    Wired to ``after_migrate`` because fixtures (which create the QR custom
    field) sync after patches run, so a patch could not rely on the column.
    Idempotent: only coupons with an empty QR field are touched.
    """
    if not frappe.db.has_column("Coupon Code", QR_FIELD):
        return

    pending = frappe.get_all(
        "Coupon Code",
        filters={QR_FIELD: ["in", ["", None]]},
        pluck="name",
    )
    if not pending:
        return

    for name in pending:
        try:
            generate_coupon_qr_code(frappe.get_doc("Coupon Code", name))
        except Exception:
            frappe.log_error(
                title="Coupon QR Backfill Failed",
                message=f"Coupon Code: {name}\n{frappe.get_traceback()}",
            )

    frappe.db.commit()


def ensure_coupon_qr_code(doc, method=None):
    """Doc event: give every coupon a QR code.

    ``coupon_code`` is ``set_only_once`` on the doctype, so it can never change
    after insert. That means the QR only ever needs generating when missing --
    there is no code-change case to keep in sync.
    """
    if doc.get(QR_FIELD):
        return

    try:
        generate_coupon_qr_code(doc)
    except Exception:
        # Never block coupon creation because the QR could not be rendered.
        frappe.log_error(
            title="Coupon QR Generation Failed",
            message=f"Coupon Code: {doc.name}\n{frappe.get_traceback()}",
        )
