"""Print formats shipped with the app.

The layout lives in print_formats/<file>.html and <file>.css, so it can be edited and reviewed in git.
sync() runs after every migrate and copies those files into the Print Format records.
Edit the files, not the Print Format in the desk: the next migrate overwrites it.
"""
import frappe

FORMATS = (
    {"name": "Hire Order Contract", "doc_type": "Hire Order Contract", "file": "hire_order_contract"},
)


def _read(file, ext):
    with open(frappe.get_app_path("thinknxg_rental", "print_formats", f"{file}.{ext}"), encoding="utf-8") as f:
        return f.read()


def _sync_one(fmt):
    values = {
        "doc_type": fmt["doc_type"],
        "standard": "No",
        "custom_format": 1,
        "print_format_type": "Jinja",
        "html": _read(fmt["file"], "html"),
        "css": _read(fmt["file"], "css"),
        "disabled": 0,
        "margin_top": 8,
        "margin_bottom": 8,
        "margin_left": 8,
        "margin_right": 8,
    }
    if frappe.db.exists("Print Format", fmt["name"]):
        doc = frappe.get_doc("Print Format", fmt["name"])
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc({"doctype": "Print Format", "name": fmt["name"], **values}).insert(ignore_permissions=True)


def sync():
    """Never let a print format problem stop a migrate: log it and carry on."""
    for fmt in FORMATS:
        try:
            _sync_one(fmt)
        except Exception:
            frappe.log_error(title=f"thinkNXG Rental: print format {fmt['name']} not synced", message=frappe.get_traceback())
