"""v2.0.2: a JCR now records which Hire Order Contract job line it reports on, so the same job type
at two locations is tracked separately. Fill that link on JCRs raised with 2.0.0 / 2.0.1."""
import frappe
from frappe.utils import flt


def execute():
	jcrs = frappe.get_all(
		"Job Completion Report",
		filters={"docstatus": ["<", 2], "contract_item": ["is", "not set"]},
		fields=["name", "hire_order_contract", "job_type", "location", "job_qty", "docstatus"],
		order_by="creation asc",
	)
	used = {}
	for j in jcrs:
		lines = frappe.get_all(
			"Hire Order Contract Item",
			filters={"parent": j.hire_order_contract, "job_type": j.job_type},
			fields=["name", "location", "qty"],
			order_by="idx asc",
		)
		if not lines:
			continue
		wanted = (j.location or "").strip().lower()
		line = (
			next((l for l in lines if wanted and (l.location or "").strip().lower() == wanted), None)
			or next((l for l in lines if flt(l.qty) - used.get(l.name, 0) > 1e-6), None)
			or lines[0]
		)
		frappe.db.set_value("Job Completion Report", j.name, "contract_item", line.name, update_modified=False)
		if j.docstatus == 1:
			used[line.name] = used.get(line.name, 0) + flt(j.job_qty)
	for name, qty in used.items():
		frappe.db.set_value("Hire Order Contract Item", name, "jcr_qty", qty, update_modified=False)
