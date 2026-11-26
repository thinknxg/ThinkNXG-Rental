import frappe
from frappe import _
from frappe.utils import nowdate

from thinknxg_rental.services import subcontracting as sc


def _check_read(hoc):
	if not frappe.has_permission("Hire Order Contract", "read", hoc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_subcontract_summary(hire_order_contract):
	"""The Subcontracting block of a Hire Order Contract (dashboard and cost summary)."""
	_check_read(hire_order_contract)
	if not frappe.has_permission("Subcontract Work Order", "read"):
		return None
	out = sc.subcontract_summary(hire_order_contract)
	from thinknxg_rental.services import subcontract_cost
	out["profitability"] = subcontract_cost.profitability(hire_order_contract)
	return out


@frappe.whitelist()
def make_subcontract_work_order(hire_order_contract):
	"""An unsaved Subcontract Work Order carrying the job lines that still have quantity to subcontract."""
	_check_read(hire_order_contract)
	frappe.has_permission("Subcontract Work Order", "create", throw=True)
	hoc = frappe.get_doc("Hire Order Contract", hire_order_contract)
	if hoc.docstatus != 1:
		frappe.throw(_("Submit the Hire Order Contract first"))
	doc = frappe.new_doc("Subcontract Work Order")
	doc.update({"hire_order_contract": hoc.name, "customer": hoc.customer, "project": hoc.project, "rental_site": hoc.rental_site, "company": hoc.company,
		"cost_center": hoc.cost_center, "contract_date": nowdate()})
	for a in sc.line_availability(hoc.name):
		if a.available_qty > 0:
			doc.append("items", {"hoc_item": a.hoc_item, "job_type": a.job_type, "item_code": a.job_type, "work_category": "Labour", "qty": a.available_qty,
				"contract_qty": a.contract_qty, "previously_subcontracted_qty": a.subcontracted_qty,
				"uom": frappe.db.get_value("Item", a.job_type, "stock_uom")})
	if not doc.items:
		frappe.throw(_("Nothing is left to subcontract on {0}").format(hoc.name))
	return doc.as_dict()


@frappe.whitelist()
def prefill(doctype, subcontract_work_order):
	"""Rows a child document starts with, taken from the approved work order: what is accepted and not yet invoiced, what is outstanding with the subcontractor."""
	if doctype not in ("Subcontract Work Progress", "Subcontract Material Return", "Subcontract Settlement"):
		frappe.throw(_("Not supported"))
	frappe.has_permission(doctype, "create", throw=True)
	swo = frappe.get_doc("Subcontract Work Order", subcontract_work_order)
	if swo.docstatus != 1:
		return []
	if doctype == "Subcontract Work Progress":
		return [{"swo_item": r.name, "job_type": r.job_type, "work_category": r.work_category, "ordered_qty": r.qty, "accepted_before": r.accepted_qty,
			"accepted_qty": 0, "rejected_qty": 0} for r in swo.items if r.accepted_qty < r.qty]
	if doctype == "Subcontract Material Return":
		return [{"item_code": k, "issued_qty": b.issued, "outstanding_qty": b.outstanding} for k, b in sc.issued_balance(swo.name).items() if b.outstanding > 0]
	return [{"swo_item": r.name, "job_type": r.job_type, "work_category": r.work_category, "accepted_qty": r.accepted_qty, "invoiced_qty": r.invoiced_qty,
		"qty": r.accepted_qty - r.invoiced_qty, "rate": r.rate} for r in swo.items if r.accepted_qty - r.invoiced_qty > 0]
