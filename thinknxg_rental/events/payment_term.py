"""Payment Term on Quotation, Sales Order and Sales Invoice: one ERPNext Payment Term for the whole amount.

ERPNext itself takes a Payment Terms Template, and a chosen template wins. Without one, a filled
Payment Term sets the payment schedule to that one term (its due date from the document date, its
invoice portion); ERPNext's own validation then works out the amounts as usual.
"""
import frappe
from frappe.utils import getdate


def apply(doc, method=None):
	term = doc.get("nxg_payment_term")
	if not term or doc.get("payment_terms_template") or doc.docstatus != 0 or doc.get("is_return"):
		return
	current = doc.get("payment_schedule") or []
	if len(current) == 1 and current[0].payment_term == term:
		return  # already set; keep a due date someone adjusted by hand
	from erpnext.controllers.accounts_controller import get_payment_term_details

	posting_date = doc.get("transaction_date") or doc.get("posting_date")
	row = get_payment_term_details(term, posting_date, doc.get("grand_total"), doc.get("base_grand_total"))
	row["payment_term"] = term  # ERPNext only names the term when it comes from a template row
	doc.set("payment_schedule", [row])
	if doc.doctype == "Sales Invoice" and row.get("due_date") and getdate(row["due_date"]) >= getdate(posting_date):
		doc.due_date = row["due_date"]
