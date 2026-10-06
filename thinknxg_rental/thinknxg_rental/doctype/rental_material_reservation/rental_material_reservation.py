import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from thinknxg_rental.services import ledger
from thinknxg_rental.services.utils import check_duplicate_items, get_bin_qty, get_reserved_for_others


class RentalMaterialReservation(Document):
	"""A soft reservation: it never posts to the stock ledger, it only reduces the quantity
	that other contracts are allowed to reserve or dispatch from the yard."""

	def validate(self):
		if not (self.hire_order or self.hire_contract):
			frappe.throw(_("Select a Hire Order or a Hire Contract"))
		if self.hire_contract and not self.hire_order:
			self.hire_order = frappe.db.get_value("Hire Order Contract", self.hire_contract, "hire_order")
		check_duplicate_items(self)
		self.set_availability()

	def set_availability(self):
		totals = frappe._dict(required=0, reserved=0, shortfall=0)
		for d in self.items:
			if flt(d.required_qty) <= 0:
				frappe.throw(_("Row #{0}: Required Qty must be greater than zero").format(d.idx))
			d.actual_qty = get_bin_qty(d.item_code, self.source_warehouse)
			d.other_reserved_qty = get_reserved_for_others(d.item_code, self.source_warehouse, reservation=self.name)
			d.available_qty = max(flt(d.actual_qty) - flt(d.other_reserved_qty), 0)
			d.reserved_qty = min(flt(d.required_qty), flt(d.available_qty))
			d.shortfall_qty = flt(d.required_qty) - flt(d.reserved_qty)
			d.dispatched_qty = 0
			d.released_qty = 0
			totals.required += flt(d.required_qty)
			totals.reserved += flt(d.reserved_qty)
			totals.shortfall += flt(d.shortfall_qty)
		self.total_required_qty = totals.required
		self.total_reserved_qty = totals.reserved
		self.total_shortfall_qty = totals.shortfall

	def before_submit(self):
		# availability may have moved since the draft was saved
		self.set_availability()
		if not self.total_reserved_qty:
			frappe.throw(_("Nothing is available to reserve. Raise a Cross Hire Order for the shortfall instead."))

	def on_submit(self):
		self.db_set("status", "Partially Reserved" if flt(self.total_shortfall_qty) > 0 else "Reserved")
		contract = self.get_contract()
		if contract:
			sync_reservations(contract)

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def get_contract(self):
		if self.hire_contract:
			return self.hire_contract
		if self.hire_order:
			return frappe.db.get_value("Hire Order Contract", {"hire_order": self.hire_order, "docstatus": 1}, "name")

	@frappe.whitelist()
	def release(self):
		"""Hand the undispatched balance back to the available pool."""
		self.check_permission("write")
		if self.docstatus != 1 or self.status in ("Released", "Dispatched"):
			frappe.throw(_("Nothing to release"))
		for d in self.items:
			d.db_set("released_qty", max(flt(d.reserved_qty) - flt(d.dispatched_qty), 0), update_modified=False)
		self.db_set("status", "Released")


def sync_reservations(hire_contract):
	"""Allocate the contract's own-stock dispatches against its reservations, oldest first (idempotent)."""
	hire_order = frappe.db.get_value("Hire Order Contract", hire_contract, "hire_order")
	dispatched = dict(
		frappe.db.sql(
			"""select item_code, sum(qty) from `tabRental Ownership Ledger`
			where position_type = %s and hire_contract = %s and movement_type = 'Dispatch' and ownership = 'Own'
			group by item_code""",
			(ledger.AT_SITE, hire_contract),
		)
	)
	filters = {"docstatus": 1}
	or_filters = {"hire_contract": hire_contract}
	if hire_order:
		or_filters["hire_order"] = hire_order
	names = frappe.get_all(
		"Rental Material Reservation", filters=filters, or_filters=or_filters, pluck="name", order_by="creation asc"
	)
	for name in names:
		doc = frappe.get_doc("Rental Material Reservation", name)
		open_balance = 0
		for d in doc.items:
			if doc.status == "Released":
				# released rows keep what was dispatched before the release
				cap = flt(d.reserved_qty) - flt(d.released_qty)
			else:
				cap = flt(d.reserved_qty)
			allocated = min(cap, flt(dispatched.get(d.item_code)))
			dispatched[d.item_code] = flt(dispatched.get(d.item_code)) - allocated
			d.db_set("dispatched_qty", allocated, update_modified=False)
			open_balance += flt(d.reserved_qty) - allocated - flt(d.released_qty)
		if doc.status != "Released":
			if open_balance <= 1e-6 and flt(doc.total_reserved_qty) > 0:
				status = "Dispatched"
			else:
				status = "Partially Reserved" if flt(doc.total_shortfall_qty) > 0 else "Reserved"
			doc.db_set("status", status, update_modified=False)


@frappe.whitelist()
def make_cross_hire_order(source_name: str, target_doc=None):
	"""Cross hire requirement = whatever the yard could not cover."""
	source = frappe.get_doc("Rental Material Reservation", source_name)
	source.check_permission("read")
	target = frappe.new_doc("Cross Hire Order")
	start = max(getdate(source.required_from or nowdate()), getdate(nowdate()))
	target.update(
		{
			"company": source.company,
			"hire_contract": source.get_contract(),
			"material_reservation": source.name,
			"order_date": nowdate(),
			"hire_from": start,
			"expected_return_date": max(getdate(source.required_to or start), start),
		}
	)
	for d in source.items:
		if flt(d.shortfall_qty) > 0:
			target.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom, "qty": d.shortfall_qty})
	if not target.items:
		frappe.throw(_("This reservation has no shortfall"))
	return target
