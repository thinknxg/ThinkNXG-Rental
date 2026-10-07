import frappe

from thinknxg_rental.services.billing import update_contract_billed_amount

# (link field on Sales Invoice, target DocType, status when it has no invoice)
LINKS = (
	("nxg_rental_billing_schedule", "Rental Billing Schedule", "Unbilled"),
	("nxg_rental_damage_settlement", "Rental Damage Settlement", "To Invoice"),
	("nxg_jcr_billing_schedule", "JCR Billing Schedule", "Pending"),
)


def _refresh(doc):
	if doc.get("nxg_rental_contract"):
		update_contract_billed_amount(doc.nxg_rental_contract)
	if doc.get("nxg_jcr") and frappe.db.exists("Job Completion Report", doc.nxg_jcr):
		from thinknxg_rental.services.jcr_billing import update_jcr_progress

		update_jcr_progress(doc.nxg_jcr)


def on_submit(doc, method=None):
	for field, doctype, _open_status in LINKS:
		if doc.get(field) and not doc.is_return:
			values = {"sales_invoice": doc.name, "status": "Invoiced"}
			if doctype == "JCR Billing Schedule":
				values["billed"] = 1
			frappe.db.set_value(doctype, doc.get(field), values)
	_refresh(doc)


def unlink(doc, method=None):
	"""Release the back-link before cancel / delete so the schedule or settlement can be re-invoiced."""
	for field, doctype, open_status in LINKS:
		name = doc.get(field)
		if name and frappe.db.get_value(doctype, name, "sales_invoice") == doc.name:
			docstatus = frappe.db.get_value(doctype, name, "docstatus")
			values = {"sales_invoice": None, "status": "Cancelled" if docstatus == 2 else open_status}
			if doctype == "JCR Billing Schedule":
				values["billed"] = 0
			frappe.db.set_value(doctype, name, values)


def on_cancel(doc, method=None):
	_refresh(doc)
