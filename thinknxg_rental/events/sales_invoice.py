import frappe

from thinknxg_rental.services.billing import update_contract_billed_amount

LINKS = (
	("nxg_rental_billing_schedule", "Rental Billing Schedule", "Unbilled"),
	("nxg_rental_damage_settlement", "Rental Damage Settlement", "To Invoice"),
)


def on_submit(doc, method=None):
	for field, doctype, _open_status in LINKS:
		if doc.get(field) and not doc.is_return:
			frappe.db.set_value(doctype, doc.get(field), {"sales_invoice": doc.name, "status": "Invoiced"})
	if doc.get("nxg_hire_contract"):
		update_contract_billed_amount(doc.nxg_hire_contract)


def unlink(doc, method=None):
	"""Release the back-link before cancel / delete so the schedule or settlement can be re-invoiced."""
	for field, doctype, open_status in LINKS:
		name = doc.get(field)
		if name and frappe.db.get_value(doctype, name, "sales_invoice") == doc.name:
			docstatus = frappe.db.get_value(doctype, name, "docstatus")
			frappe.db.set_value(
				doctype, name, {"sales_invoice": None, "status": open_status if docstatus == 1 else "Cancelled"}
			)


def on_cancel(doc, method=None):
	if doc.get("nxg_hire_contract"):
		update_contract_billed_amount(doc.nxg_hire_contract)
