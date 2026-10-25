"""Payment Term on Quotation and Sales Invoice: one ERPNext Payment Term for the whole amount.

ERPNext itself takes a Payment Terms Template. When the custom Payment Term field is filled, the
payment schedule is set to that one term (its due date from the document date, its invoice portion)
and the template is cleared; ERPNext's own validation then works out the amounts as usual.
"""
import frappe
from frappe.utils import getdate


def apply(doc, method=None):
	term = doc.get("nxg_payment_term")
	if not term or doc.docstatus != 0 or doc.get("is_return"):
		return
	current = doc.get("payment_schedule") or []
	if len(current) == 1 and current[0].payment_term == term and not doc.get("payment_terms_template"):
		return  # already set; keep a due date someone adjusted by hand
	from erpnext.controllers.accounts_controller import get_payment_term_details

	posting_date = doc.get("transaction_date") or doc.get("posting_date")
	row = get_payment_term_details(term, posting_date, doc.get("grand_total"), doc.get("base_grand_total"))
	doc.payment_terms_template = None
	doc.set("payment_schedule", [row])
	if doc.doctype == "Sales Invoice" and row.get("due_date") and getdate(row["due_date"]) >= getdate(posting_date):
		doc.due_date = row["due_date"]
