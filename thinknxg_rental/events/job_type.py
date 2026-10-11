import frappe
from frappe import _


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def job_type_query(doctype, txt, searchfield, start, page_len, filters):
    """Link search for job_type fields: active Job Types only (value is the service Item code)."""
    return frappe.db.sql(
        """select name, job_type_name from `tabJob Type`
        where disabled = 0 and (name like %(txt)s or job_type_name like %(txt)s)
        order by name limit %(start)s, %(page_len)s""",
        {"txt": f"%{txt}%", "start": start, "page_len": page_len},
    )


@frappe.whitelist()
def duplicate_job_type(source, new_item_code, new_item_name=None, new_item_group=None):
    """Copy a Job Type: a new non-stock service Item plus a Job Type with the same rental items."""
    frappe.has_permission("Job Type", "create", throw=True)
    new_item_code = (new_item_code or "").strip()
    if not new_item_code:
        frappe.throw(_("Enter the new Job Type Item Code"))
    if frappe.db.exists("Item", new_item_code) or frappe.db.exists("Job Type", new_item_code):
        frappe.throw(_("{0} already exists").format(frappe.bold(new_item_code)))

    src = frappe.get_doc("Job Type", source)
    item = frappe.copy_doc(frappe.get_doc("Item", src.item_code))
    item.item_code = new_item_code
    item.item_name = (new_item_name or "").strip() or new_item_code
    item.description = item.item_name
    if new_item_group:
        item.item_group = new_item_group
    if item.meta.has_field("nxg_is_job_type_item"):
        item.nxg_is_job_type_item = 0
        item.set("nxg_job_type_items", [])
    item.insert()

    doc = frappe.new_doc("Job Type")
    doc.item_code = item.name
    doc.description = src.description
    for r in src.rental_items:
        doc.append("rental_items", {"item_code": r.item_code, "qty": r.qty})
    doc.insert()
    return doc.name


def get_job_type_items(job_type):
    """[{item_code, item_name, uom, qty}] for one job of this type."""
    if not frappe.db.exists("Job Type", job_type):
        frappe.throw(_("{0} is not a Job Type").format(frappe.bold(job_type)))
    return frappe.get_all(
        "Job Type Rental Item",
        filters={"parent": job_type, "parenttype": "Job Type", "parentfield": "rental_items"},
        fields=["item_code", "item_name", "uom", "qty"],
        order_by="idx asc",
    )
