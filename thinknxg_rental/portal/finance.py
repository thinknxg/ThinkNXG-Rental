"""Command Center actions for security deposits, advances and pro forma invoices.

Each action posts a Rental Contract Payment through services/deposits.py, the same as the desk dialogs: the
same limits, approval (a refund or deduction by a user who cannot approve waits as Pending Approval), and one
Journal Entry per transaction. The action then opens the receipt in the Command Center.
"""
import frappe
from frappe import _
from frappe.utils import flt, nowdate

from thinknxg_rental.services import deposits as D

DEDUCTION_REASONS = ["", "Damage", "Missing Material", "Unpaid Rental", "Other"]


def _post(transaction_type, source_field, source, values):
	payload = {"transaction_type": transaction_type, source_field: source, "posting_date": values.pop("posting_date", None) or nowdate()}
	payload.update({k: v for k, v in values.items() if v not in (None, "")})
	payload["amount"] = flt(payload.get("amount"))
	return D.make(payload).name


def _action(transaction_type, source_field):
	def run(**kwargs):
		source = kwargs.pop(source_field)
		return _post(transaction_type, source_field, source, kwargs)

	run.__name__ = f"post_{transaction_type.lower().replace(' ', '_')}"
	return run


# rental contract
collect_deposit = _action(D.D_COLLECT, "rental_contract")
refund_deposit = _action(D.D_REFUND, "rental_contract")
deduct_deposit = _action(D.D_DEDUCT, "rental_contract")
collect_advance = _action(D.A_COLLECT, "rental_contract")
adjust_advance = _action(D.A_ADJUST, "rental_contract")
refund_advance = _action(D.A_REFUND, "rental_contract")
# pro forma invoice (before the contract exists)
pro_forma_advance = _action(D.A_COLLECT, "pro_forma_invoice")
pro_forma_deposit = _action(D.D_COLLECT, "pro_forma_invoice")


def adjust_advance_on_invoice(sales_invoice, amount, posting_date=None):
	"""Adjust Advance on a rental invoice: the invoice's contract gives the advance."""
	contract = frappe.db.get_value("Sales Invoice", sales_invoice, "nxg_rental_contract")
	if not contract:
		frappe.throw(_("Sales Invoice {0} is not a rental contract invoice").format(sales_invoice))
	return _post(D.A_ADJUST, "rental_contract", contract, {"sales_invoice": sales_invoice, "amount": amount, "posting_date": posting_date})


# ------------------------------------------------------------------ ask panels
def _money(label, default=None):
	"""Amount and posting date: the first two fields of every deposit and advance panel."""
	return [{"fieldname": "amount", "label": label, "fieldtype": "Currency", "reqd": 1, "default": flt(default) or None},
		{"fieldname": "posting_date", "label": "Posting date", "fieldtype": "Date", "reqd": 1, "default": nowdate()}]


def _cash(default_mode="Cash"):
	return [
		{"fieldname": "mode_of_payment", "label": "Mode of payment", "fieldtype": "Link", "options": "Mode of Payment", "reqd": 1, "default": default_mode},
		{"fieldname": "account", "label": "Bank / cash account (optional)", "fieldtype": "Link", "options": "Account",
			"filters": {"company": "$company", "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]}},
		{"fieldname": "reference_no", "label": "Transaction / cheque reference", "fieldtype": "Data"},
		{"fieldname": "reference_date", "label": "Reference date", "fieldtype": "Date"},
	]


def _invoice():
	return {"fieldname": "sales_invoice", "label": "Sales invoice", "fieldtype": "Link", "options": "Sales Invoice", "reqd": 1,
		"filters": {"customer": "$customer", "company": "$company", "docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}}


REMARKS = {"fieldname": "remarks", "label": "Remarks", "fieldtype": "Small Text", "wide": 1}


def remaining(d, fund):
	"""Still to collect on a contract or pro forma invoice (None: nothing asked): what the server will accept."""
	if d.doctype == "Rental Pro Forma Invoice":
		r = D.remaining_to_collect(pro_forma_invoice=d.name)
	else:
		r = D.remaining_to_collect(rental_contract=d.name)
	return r[fund]


def can_collect(d, fund):
	left = remaining(d, fund)
	return left is None or left > 0


def ask_collect_deposit(d):
	return [*_money("Deposit received now", remaining(d, "deposit")), *_cash(), REMARKS]


def ask_refund_deposit(d):
	return [*_money("Refund amount", d.get("deposit_balance")), *_cash(), REMARKS]


def ask_deduct_deposit(d):
	return [*_money("Deduction amount"), _invoice(),
		{"fieldname": "deduction_reason", "label": "Deduction reason", "fieldtype": "Select", "reqd": 1, "choices": DEDUCTION_REASONS},
		{"fieldname": "damage_settlement", "label": "Damage settlement", "fieldtype": "Link", "options": "Rental Damage Settlement",
			"filters": {"rental_contract": d.get("name"), "docstatus": 1}}, REMARKS]


def ask_collect_advance(d):
	return [*_money("Advance received now", remaining(d, "advance")), *_cash(), REMARKS]


def ask_adjust_advance(d):
	return [*_money("Advance to adjust", d.get("advance_available")), _invoice(), REMARKS]


def ask_refund_advance(d):
	return [*_money("Refund amount", d.get("advance_available")), *_cash(), REMARKS]


def ask_pro_forma_advance(d):
	return [*_money("Advance received now", remaining(d, "advance")), *_cash(), REMARKS]


def ask_pro_forma_deposit(d):
	return [*_money("Deposit received now", remaining(d, "deposit")), *_cash(), REMARKS]


def ask_invoice_advance(d):
	info = D.adjustable_advance(d.name) or {}
	return [*_money(_("Advance to adjust (available {0})").format(frappe.format(info.get("advance_available"), {"fieldtype": "Currency",
		"options": d.get("currency")})), info.get("suggested"))]


def invoice_has_advance(d):
	if d.docstatus != 1 or d.is_return or not d.get("nxg_rental_contract") or flt(d.outstanding_amount) <= 0:
		return False
	return flt(frappe.db.get_value("Rental Contract", d.nxg_rental_contract, "advance_available")) > 0


def whatsapp_url(doc):
	"""Share link for a pro forma invoice (the message is written by the document itself)."""
	from urllib.parse import quote

	if doc.docstatus != 1 or not frappe.has_permission(doc.doctype, "read", doc=doc):
		return None
	try:
		m = doc.whatsapp_message()
	except frappe.ValidationError:
		return None
	return f"https://wa.me/{m['mobile']}?text={quote(m['text'])}"
