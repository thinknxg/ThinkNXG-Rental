import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate

from thinknxg_rental.services import billing


class RentalBillingSchedule(Document):
	def validate(self):
		if getdate(self.to_date) < getdate(self.from_date):
			frappe.throw(_("Billing To cannot be before Billing From"))
		self._contract = frappe.get_doc("Hire Order Contract", self.hire_contract)
		if self._contract.docstatus != 1:
			frappe.throw(_("Contract {0} is not submitted").format(self.hire_contract))
		# lines always come from the ledger so a schedule can never drift from what was on hire
		self.set("items", [])
		for line in billing.compute_lines(self._contract, self.from_date, self.to_date):
			self.append("items", line)
		self.total_amount = sum(flt(d.amount) for d in self.items)

	def before_submit(self):
		if not self.items:
			frappe.throw(_("Nothing was on hire in this period"))
		expected = (
			add_days(self._contract.last_billed_upto, 1)
			if self._contract.last_billed_upto
			else self._contract.billing_start_date
		)
		if not expected or getdate(self.from_date) != getdate(expected):
			frappe.throw(
				_("Billing must continue from {0} for contract {1}").format(
					frappe.format(expected, {"fieldtype": "Date"}), self.hire_contract
				)
			)

	def on_submit(self):
		self.db_set("status", "Unbilled")
		billing.set_billing_pointers(self._contract, self.to_date)

	def on_cancel(self):
		contract = frappe.get_doc("Hire Order Contract", self.hire_contract)
		if not contract.last_billed_upto or getdate(contract.last_billed_upto) != getdate(self.to_date):
			frappe.throw(_("Only the latest billing schedule of a contract can be cancelled"))
		if self.sales_invoice and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 0:
			frappe.throw(_("Delete draft Sales Invoice {0} first").format(self.sales_invoice))
		previous = add_days(self.from_date, -1)
		start = contract.billing_start_date
		billing.set_billing_pointers(contract, previous if start and getdate(previous) >= getdate(start) else None)
		contract.reload()
		if not contract.last_billed_upto and start:
			contract.db_set("next_billing_date", add_days(billing.get_period_end(contract, start), 1), update_modified=False)
		self.db_set("status", "Cancelled")
