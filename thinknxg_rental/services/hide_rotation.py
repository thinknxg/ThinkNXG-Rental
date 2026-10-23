import frappe

FIELDS = {
    "JCR Job Line": ["nxg_rotation", "nxg_rotations_done", "nxg_balance_rotation", "nxg_rotations_completed", "nxg_duration"],
    "Hire Order Contract Item": ["nxg_duration"],
    "Quotation Item": ["nxg_duration"],
}
PROPS = ["hidden", "in_list_view", "read_only", "default"]


def run():
    """Undo the earlier hiding of the rotation fields. Removes only the property setters that hid them; idempotent."""
    jcr_line = frappe.get_meta("Job Completion Report").get_field("job_lines").options
    for dt, names in FIELDS.items():
        dt = jcr_line if dt == "JCR Job Line" else dt
        for fn in names:
            for prop in PROPS:
                frappe.db.delete("Property Setter", {"name": f"{dt}-{fn}-{prop}"})
        frappe.clear_cache(doctype=dt)
