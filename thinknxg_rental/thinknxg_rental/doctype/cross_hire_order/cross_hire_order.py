import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate

from thinknxg_rental.services import cross_hire, ledger
from thinknxg_rental.services.utils import as_system, check_duplicate_items, estimate_amount, require_setting


class CrossHireOrder(Document):
	def validate(self):
		if getdate(self.expected_return_date) < getdate(self.hire_from):
			frappe.throw(_("Expected Return Date cannot be before Hire From"))
		self.expected_hire_days = date_diff(self.expected_return_date, self.hire_from) + 1
		if self.rental_contract:
			contract = frappe.db.get_value(
				"Rental Contract", self.rental_contract, ["customer", "rental_site", "project", "company"], as_dict=True
			)
			if contract.company != self.company:
				frappe.throw(_("Contract {0} belongs to company {1}").format(self.rental_contract, contract.company))
			self.customer, self.rental_site, self.project = contract.customer, contract.rental_site, contract.project
		self.set_receipt_warehouse()
		check_duplicate_items(self)
		self.total_qty = self.estimated_amount = 0
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
			if not frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
				frappe.throw(
					_("Row #{0}: {1} must be a stock item. Cross-hired equipment uses the same Item as own stock.").format(d.idx, d.item_code)
				)
			d.rate_basis = d.rate_basis or self.rate_basis or "Monthly"
			d.expected_hire_days = cint(d.expected_hire_days) or self.expected_hire_days
			d.estimated_amount = estimate_amount(d.qty, d.expected_hire_days, d.rate_basis, d.rate)
			self.total_qty += flt(d.qty)
			self.estimated_amount += flt(d.estimated_amount)

	def set_receipt_warehouse(self):
		if self.receive_at == "Direct to Site":
			if not self.rental_site:
				frappe.throw(_("Select the customer Rental Contract to receive cross-hired material directly at site"))
			self.receipt_warehouse = frappe.db.get_value("Rental Site", self.rental_site, "cross_hire_site_warehouse")
		else:
			self.receipt_warehouse = require_setting("cross_hire_yard_warehouse")
		if not self.receipt_warehouse:
			frappe.throw(_("Could not determine the cross hire receipt warehouse"))

	def on_submit(self):
		self.db_set("status", "To Receive")
		self.db_set("purchase_order", cross_hire.create_purchase_order(self))

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		if self.purchase_order:
			po = frappe.get_doc("Purchase Order", self.purchase_order)
			if po.docstatus == 1:
				po.flags.ignore_permissions = True
				with as_system():
					po.cancel()
			elif po.docstatus == 0:
				frappe.delete_doc("Purchase Order", po.name, ignore_permissions=True, force=True)
				self.db_set("purchase_order", None)

	@frappe.whitelist()
	def complete(self):
		"""Everything is back with the supplier (or settled as lost): close the order and its Purchase Order."""
		self.check_permission("write")
		ledger.update_cross_hire_progress(self.name)
		self.reload()
		on_hire = sum(flt(d.on_hire_qty) for d in self.items)
		if on_hire > 0:
			frappe.throw(_("{0} units are still on hire from the supplier").format(on_hire))
		self.db_set("status", "Completed")
		if self.purchase_order:
			po = frappe.get_doc("Purchase Order", self.purchase_order)
			if po.docstatus == 1 and po.status not in ("Closed", "Completed"):
				with as_system():
					po.update_status("Closed")
