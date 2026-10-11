import frappe

LEGACY_FIELDS = ["nxg_job_type_items", "nxg_job_type_section", "nxg_is_job_type_item"]


def backfill_job_type_fields():
    """Fill Item Name and Item Group on Job Types saved before those fields existed."""
    frappe.db.sql(
        """update `tabJob Type` jt join `tabItem` i on i.name = jt.item_code
        set jt.item_name = i.item_name, jt.job_type_name = i.item_name, jt.item_group = i.item_group
        where ifnull(jt.item_name, '') = '' or ifnull(jt.item_group, '') = ''"""
    )


def run():
    """Idempotent: turn flagged Items into Job Types, then drop the old Item fields once all are copied."""
    backfill_job_type_fields()
    if not frappe.db.has_column("Item", "nxg_is_job_type_item"):
        return
    items = frappe.get_all("Item", filters={"nxg_is_job_type_item": 1, "is_stock_item": 0}, fields=["name", "description"])
    for it in items:
        if frappe.db.exists("Job Type", it.name):
            continue
        rows = frappe.get_all(
            "Job Type Rental Item",
            filters={"parent": it.name, "parenttype": "Item", "parentfield": "nxg_job_type_items"},
            fields=["item_code", "qty"],
            order_by="idx asc",
        )
        doc = frappe.new_doc("Job Type")
        doc.item_code = it.name
        doc.description = it.description
        for r in rows:
            doc.append("rental_items", {"item_code": r.item_code, "qty": r.qty})
        doc.flags.from_migration = True
        doc.insert(ignore_permissions=True)

    # safety: only remove the legacy fields when every flagged Item has its Job Type
    flagged = frappe.get_all("Item", filters={"nxg_is_job_type_item": 1}, pluck="name")
    if all(frappe.db.exists("Job Type", n) for n in flagged):
        for fn in LEGACY_FIELDS:
            name = frappe.db.get_value("Custom Field", {"dt": "Item", "fieldname": fn})
            if name:
                frappe.delete_doc("Custom Field", name, force=True)
    frappe.db.commit()
