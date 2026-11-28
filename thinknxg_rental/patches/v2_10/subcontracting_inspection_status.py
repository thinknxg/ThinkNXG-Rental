"""Subcontracting v2: Work Progress records made before inspections existed get the inspection result their
accepted / rejected quantities already stand for. Only a status field is written; quantities and ledgers are untouched."""
import frappe
from frappe.utils import flt


def execute():
	if not frappe.db.has_column("Subcontract Work Progress", "inspection_status"):
		return
	for name in frappe.get_all("Subcontract Work Progress", filters={"docstatus": 1, "inspection_status": ["in", ["", None, "Under Inspection"]]}, pluck="name"):
		rows = frappe.get_all("Subcontract Progress Item", filters={"parent": name}, fields=["accepted_qty", "rejected_qty"])
		acc = sum(flt(r.accepted_qty) for r in rows)
		rej = sum(flt(r.rejected_qty) for r in rows)
		status = ("Accepted" if not rej else "Partially Accepted") if acc else "Rejected"
		frappe.db.set_value("Subcontract Work Progress", name, "inspection_status", status, update_modified=False)
	for name in frappe.get_all("Subcontract Work Progress", filters={"docstatus": 0, "inspection_status": ["in", ["", None]]}, pluck="name"):
		frappe.db.set_value("Subcontract Work Progress", name, "inspection_status", "Under Inspection", update_modified=False)
