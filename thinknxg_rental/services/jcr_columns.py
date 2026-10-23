import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

SHOW = ["location", "nxg_balance_qty", "contract_end_date", "dismantle_date", "nxg_duration", "nxg_rotation", "nxg_balance_rotation"]


def run():
    """Show these JCR Job Line fields in the grid by default. Idempotent; runs on every migrate."""
    dt = frappe.get_meta("Job Completion Report").get_field("job_lines").options
    meta = frappe.get_meta(dt)
    for fn in SHOW:
        if meta.has_field(fn):
            make_property_setter(dt, fn, "in_list_view", 1, "Check", validate_fields_for_doctype=False)
            make_property_setter(dt, fn, "columns", "1", "Int", validate_fields_for_doctype=False)
    frappe.clear_cache(doctype=dt)
