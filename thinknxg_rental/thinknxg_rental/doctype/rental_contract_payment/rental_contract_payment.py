import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_rental.services import deposits


class RentalContractPayment(Document):
	def validate(self):
		deposits.validate(self)

	def before_submit(self):
		deposits.before_submit(self)

	def on_submit(self):
		deposits.on_submit(self)

	def before_cancel(self):
		deposits.before_cancel(self)

	def on_cancel(self):
		deposits.on_cancel(self)

	def on_trash(self):
		if self.docstatus == 1:
			frappe.throw(_("A posted transaction cannot be deleted: cancel it"))


@frappe.whitelist()
def get_balances(rental_contract: str | None = None, hire_order: str | None = None, pro_forma_invoice: str | None = None):
	for doctype, name in (("Rental Contract", rental_contract), ("Hire Order", hire_order), ("Rental Pro Forma Invoice", pro_forma_invoice)):
		if name:
			frappe.get_doc(doctype, name).check_permission("read")
	return deposits.balances(rental_contract, hire_order, pro_forma_invoice)


@frappe.whitelist(methods=["POST"])
def create(values: str | dict):
	"""Collection, refund, deduction or adjustment from the contract or invoice dialogs: posted at once, except a
	refund or deduction by a user who cannot approve it, which waits as Pending Approval."""
	values = frappe.parse_json(values) if isinstance(values, str) else values
	frappe.has_permission(deposits.DOCTYPE, "create", throw=True)
	doc = deposits.make(values)
	return {"name": doc.name, "status": doc.status, "docstatus": doc.docstatus}


@frappe.whitelist()
def get_history(rental_contract: str, fund: str | None = None):
	frappe.get_doc("Rental Contract", rental_contract).check_permission("read")
	return deposits.history(rental_contract, fund)


@frappe.whitelist()
def get_invoice_advance(sales_invoice: str):
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")
	return deposits.adjustable_advance(sales_invoice)


@frappe.whitelist()
def get_payment_account(mode_of_payment: str, company: str):
	return deposits.payment_account(mode_of_payment, company)
