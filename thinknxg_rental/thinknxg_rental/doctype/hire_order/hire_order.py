import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request import set_request_reference
from thinknxg_rental.services.utils import (
	check_duplicate_items,
	estimate_amount,
	get_available_qty,
	get_item_rental_details,
	get_settings,
)


class HireOrder(Document):
	def validate(self):
		if getdate(self.expected_return_date) < getdate(self.required_from):
			frappe.throw(_("Expected Return Date cannot be before Required From"))
		self.expected_hire_days = date_diff(self.expected_return_date, self.required_from) + 1
		if self.rental_site and frappe.db.get_value("Rental Site", self.rental_site, "customer") != self.customer:
			frappe.throw(_("Rental Site {0} does not belong to customer {1}").format(self.rental_site, self.customer))
		check_duplicate_items(self)
		self.set_item_values()

	def set_item_values(self):
		yard = get_settings().rental_yard_warehouse
		totals = frappe._dict(qty=0, amount=0, deposit=0, replacement=0, shortfall=0)
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
			d.rate_basis = d.rate_basis or self.rate_basis or "Monthly"
			if not flt(d.rate) or not d.uom:
				details = get_item_rental_details(d.item_code, self.customer, d.rate_basis, self.order_date, yard)
				d.uom = d.uom or details["uom"]
				d.rate = flt(d.rate) or details["rate"]
				d.security_deposit_rate = flt(d.security_deposit_rate) or details["security_deposit_rate"]
				d.replacement_value = flt(d.replacement_value) or details["replacement_value"]
			d.expected_hire_days = cint(d.expected_hire_days) or self.expected_hire_days
			d.estimated_amount = estimate_amount(d.qty, d.expected_hire_days, d.rate_basis, d.rate)
			d.security_deposit = flt(d.qty) * flt(d.security_deposit_rate)
			if self.docstatus == 0:
				d.available_qty = max(get_available_qty(d.item_code, yard), 0) if yard else 0
				d.shortfall_qty = max(flt(d.qty) - flt(d.available_qty), 0)
			totals.qty += flt(d.qty)
			totals.amount += flt(d.estimated_amount)
			totals.deposit += flt(d.security_deposit)
			totals.replacement += flt(d.qty) * flt(d.replacement_value)
			totals.shortfall += flt(d.shortfall_qty)
		self.total_qty = totals.qty
		self.estimated_amount = totals.amount
		self.total_security_deposit = totals.deposit
		self.total_replacement_value = totals.replacement
		self.total_shortfall_qty = totals.shortfall

	def on_submit(self):
		self.db_set("status", "Open")
		set_request_reference(self)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		set_request_reference(self, completed=False)


@frappe.whitelist()
def make_contract(source_name: str, target_doc=None):
	def post_process(source, target):
		settings = get_settings()
		target.contract_date = nowdate()
		target.start_date = source.required_from
		target.end_date = source.expected_return_date
		target.security_deposit = source.total_security_deposit
		target.grace_days = cint(settings.default_grace_days)
		target.billing_cycle = source.billing_cycle or settings.default_billing_cycle or "Monthly"

	return get_mapped_doc(
		"Hire Order",
		source_name,
		{
			"Hire Order": {
				"doctype": "Hire Order Contract",
				"field_map": {"name": "hire_order"},
				"validation": {"docstatus": ["=", 1]},
			},
			"Hire Order Item": {"doctype": "Hire Contract Item"},
		},
		target_doc,
		post_process,
	)


@frappe.whitelist()
def make_reservation(source_name: str, target_doc=None):
	def post_process(source, target):
		target.reservation_date = nowdate()
		target.required_to = source.expected_return_date
		target.source_warehouse = get_settings().rental_yard_warehouse

	return get_mapped_doc(
		"Hire Order",
		source_name,
		{
			"Hire Order": {
				"doctype": "Rental Material Reservation",
				"field_map": {"name": "hire_order"},
				"validation": {"docstatus": ["=", 1]},
			},
			"Hire Order Item": {"doctype": "Rental Material Reservation Item", "field_map": {"qty": "required_qty"}},
		},
		target_doc,
		post_process,
	)
