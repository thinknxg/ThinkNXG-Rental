import frappe
from frappe.utils import flt

from thinknxg_rental.services.billing import update_contract_billed_amount

# (link field on Sales Invoice, target DocType, status when it has no invoice)
LINKS = (
	("nxg_rental_billing_schedule", "Rental Billing Schedule", "Unbilled"),
	("nxg_rental_damage_settlement", "Rental Damage Settlement", "To Invoice"),
)
JCR_SCHEDULE = "JCR Billing Schedule"


def _jcr_refs(doc):
	"""JCRs and JCR billing schedules on an invoice: the header links (single-schedule invoices,
	older invoices) plus the row-level links of combined invoices."""
	jcrs, schedules = [], []
	for value, target in ((doc.get("nxg_jcr"), jcrs), (doc.get("nxg_jcr_billing_schedule"), schedules)):
		if value and value not in target:
			target.append(value)
	for row in doc.get("items") or []:
		if row.get("nxg_jcr") and row.nxg_jcr not in jcrs:
			jcrs.append(row.nxg_jcr)
		if row.get("nxg_jcr_billing_schedule") and row.nxg_jcr_billing_schedule not in schedules:
			schedules.append(row.nxg_jcr_billing_schedule)
	return jcrs, schedules


def _refresh(doc):
	jcrs, _schedules = _jcr_refs(doc)
	contracts = []
	if doc.get("nxg_rental_contract"):
		contracts.append(doc.nxg_rental_contract)
	for jcr in jcrs:
		contract = frappe.db.get_value("Job Completion Report", jcr, "rental_contract")
		if contract and contract not in contracts:
			contracts.append(contract)
	for contract in contracts:
		update_contract_billed_amount(contract)
	for jcr in jcrs:
		if frappe.db.exists("Job Completion Report", jcr):
			from thinknxg_rental.services.jcr_billing import update_jcr_progress

			update_jcr_progress(jcr)


def validate(doc, method=None):
	"""Keep the computed job-billing amounts. ERPNext re-fetches item prices while validating, which
	would overwrite them, so the locked values written when the invoice was built are put back."""
	changed = False
	for row in doc.get("items") or []:
		if not row.get("nxg_row_type") or row.get("nxg_locked_rate") is None:
			continue
		if flt(row.rate) != flt(row.nxg_locked_rate):
			row.rate = flt(row.nxg_locked_rate)
			row.price_list_rate = flt(row.nxg_locked_rate)
			row.discount_percentage = 0
			row.discount_amount = 0
			changed = True
	if changed:
		doc.calculate_taxes_and_totals()
		if hasattr(doc, "set_total_in_words"):
			doc.set_total_in_words()


def on_submit(doc, method=None):
	if not doc.is_return:
		for field, doctype, _open_status in LINKS:
			if doc.get(field):
				frappe.db.set_value(doctype, doc.get(field), {"sales_invoice": doc.name, "status": "Invoiced"})
		for name in _jcr_refs(doc)[1]:
			frappe.db.set_value(JCR_SCHEDULE, name, {"sales_invoice": doc.name, "status": "Invoiced", "billed": 1})
	_refresh(doc)


def unlink(doc, method=None):
	"""Release the back-link before cancel / delete so the schedule or settlement can be re-invoiced."""
	for field, doctype, open_status in LINKS:
		name = doc.get(field)
		if name and frappe.db.get_value(doctype, name, "sales_invoice") == doc.name:
			docstatus = frappe.db.get_value(doctype, name, "docstatus")
			frappe.db.set_value(doctype, name, {"sales_invoice": None, "status": "Cancelled" if docstatus == 2 else open_status})
	for name in _jcr_refs(doc)[1]:
		if frappe.db.get_value(JCR_SCHEDULE, name, "sales_invoice") == doc.name:
			frappe.db.set_value(JCR_SCHEDULE, name, {"sales_invoice": None, "status": "Pending", "billed": 0})


def on_cancel(doc, method=None):
	_refresh(doc)
