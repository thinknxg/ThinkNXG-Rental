"""Job Type items: non-stock Items that stand for a job (for example External Scaffolding) and
carry the list of physical rental items one job needs."""
import frappe
from frappe import _
from frappe.utils import cint, flt


def validate(doc, method=None):
	rows = doc.get("nxg_job_type_items") or []
	if not cint(doc.get("nxg_is_job_type_item")):
		return
	if cint(doc.is_stock_item):
		frappe.throw(_("A Job Type Item must be a non-stock item. Untick Maintain Stock."))
	if cint(doc.is_fixed_asset):
		frappe.throw(_("A Job Type Item cannot be a fixed asset."))
	if not rows:
		frappe.throw(_("Add the physical rental items for this job type under Job Type Rental Items."))
	seen = set()
	for d in rows:
		if d.item_code == doc.name:
			frappe.throw(_("Row #{0}: a job type cannot contain itself").format(d.idx))
		if d.item_code in seen:
			frappe.throw(_("Row #{0}: {1} is listed twice").format(d.idx, d.item_code))
		seen.add(d.item_code)
		if not frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
			frappe.throw(_("Row #{0}: {1} must be a stock item (Maintain Stock)").format(d.idx, frappe.bold(d.item_code)))
		if flt(d.qty) <= 0:
			frappe.throw(_("Row #{0}: Qty per Job must be greater than zero").format(d.idx))


def get_job_type_items(job_type):
	"""[{item_code, item_name, uom, qty}] for one job of this type."""
	if not cint(frappe.get_cached_value("Item", job_type, "nxg_is_job_type_item")):
		frappe.throw(_("{0} is not a Job Type Item").format(frappe.bold(job_type)))
	return frappe.get_all(
		"Job Type Rental Item",
		filters={"parent": job_type, "parenttype": "Item", "parentfield": "nxg_job_type_items"},
		fields=["item_code", "item_name", "uom", "qty"],
		order_by="idx asc",
	)
