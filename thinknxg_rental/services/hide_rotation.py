import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

FIELDS = {
    "JCR Job Line": ["nxg_rotation", "nxg_rotations_done", "nxg_balance_rotation", "nxg_rotations_completed", "nxg_duration"],
    "Hire Order Contract Item": ["nxg_duration"],
    "Quotation Item": ["nxg_duration"],
}
PROPS = ["hidden", "in_list_view", "read_only"]


def run():
    """Keep the rotation fields visible and editable (removes the property setters that once hid them), and make
    Rotation default to 1 on Quotation Item rows. Idempotent; runs on every migrate."""
    jcr_line = frappe.get_meta("Job Completion Report").get_field("job_lines").options
    for dt, names in FIELDS.items():
        dt = jcr_line if dt == "JCR Job Line" else dt
        for fn in names:
            for prop in PROPS:
                frappe.db.delete("Property Setter", {"name": f"{dt}-{fn}-{prop}"})
        frappe.clear_cache(doctype=dt)
    make_property_setter("Quotation Item", "nxg_duration", "default", "1", "Text", validate_fields_for_doctype=False)
    frappe.clear_cache(doctype="Quotation Item")
