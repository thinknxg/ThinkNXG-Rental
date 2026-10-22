import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def run():
    """Hide the rotation fields. Idempotent; runs on every migrate, changes no records."""
    jcr_line = frappe.get_meta("Job Completion Report").get_field("job_lines").options
    fields = {
        jcr_line: ["nxg_rotation", "nxg_rotations_done", "nxg_balance_rotation", "nxg_rotations_completed", "nxg_duration"],
        "Hire Order Contract Item": ["nxg_duration"],
        "Quotation Item": ["nxg_duration"],
    }
    for dt, names in fields.items():
        meta = frappe.get_meta(dt)
        for fn in names:
            if not meta.has_field(fn):
                continue
            make_property_setter(dt, fn, "hidden", 1, "Check", validate_fields_for_doctype=False)
            make_property_setter(dt, fn, "in_list_view", 0, "Check", validate_fields_for_doctype=False)
            if fn == "nxg_duration":
                make_property_setter(dt, fn, "default", "1", "Text", validate_fields_for_doctype=False)
                make_property_setter(dt, fn, "read_only", 1, "Check", validate_fields_for_doctype=False)
        frappe.clear_cache(doctype=dt)
