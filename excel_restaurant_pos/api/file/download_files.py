import os
from urllib.parse import unquote

import frappe
from frappe.utils import get_files_path

from excel_restaurant_pos.utils import rate_limit_guest


@frappe.whitelist(allow_guest=True)
def download_public_file():
    """
    Stream a public file as an attachment so the browser downloads it
    (Content-Disposition: attachment) instead of opening it inline.

    Served through Python in both dev and production, so it behaves the
    same everywhere and needs no nginx/CORS changes.

    Query params:
        file_url: a public file url, e.g. /files/My-Manual.pdf
    """
    rate_limit_guest("download_public_file", limit=30)

    file_url = frappe.form_dict.get("file_url")
    if not file_url:
        frappe.throw("file_url is required")

    # Only public files are allowed
    if not file_url.startswith("/files/"):
        frappe.throw("Only public files can be downloaded")

    file_name = os.path.basename(unquote(file_url))

    # Resolve inside the public files dir and guard against path traversal
    base_dir = os.path.realpath(get_files_path(is_private=0))
    file_path = os.path.realpath(os.path.join(base_dir, file_name))
    if not file_path.startswith(base_dir + os.sep) or not os.path.isfile(file_path):
        frappe.throw("File not found", frappe.DoesNotExistError)

    with open(file_path, "rb") as f:
        content = f.read()

    frappe.local.response.filename = file_name
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"
