import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services.utils import get_profile, get_settings
from thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request import set_request_reference


class HireOffHireNote(Document):
	def validate(self):
		self._contract = frappe.get_doc("Hire Order Contract", self.hire_contract)
		if self._contract.docstatus != 1 or self._contract.status in ("Completed", "Cancelled"):
			frappe.throw(_("Contract {0} is not live").format(self.hire_contract))
		for field in ("customer", "customer_name", "rental_site", "project"):
			self.set(field, self._contract.get(field))
		self.set_last_billable_date()
		self.validate_items()

	def set_last_billable_date(self):
		"""Returned within the grace period: billing stops on the off-hire date.
		Returned late: billing runs up to the day before the material actually came back.
		Example: off-hire 31-Oct, grace 2 days, returned 03-Nov -> 01-Nov and 02-Nov are billable."""
		off_hire, returned = getdate(self.off_hire_date), getdate(self.return_date)
		if returned < off_hire:
			frappe.throw(_("Material Return Date cannot be before the Off-Hire Date"))
		if self.is_new() and not cint(self.grace_days):
			self.grace_days = cint(self._contract.grace_days)
		if returned <= add_days(off_hire, cint(self.grace_days)):
			last = off_hire
		else:
			last = add_days(returned, -1)
		start = self._contract.billing_start_date
		if start and cint(self._contract.minimum_hire_days):
			last = max(last, add_days(getdate(start), cint(self._contract.minimum_hire_days) - 1))
		if start and last < getdate(start):
			last = getdate(start)
		self.last_billable_date = last
		billed = self._contract.last_billed_upto
		if billed and last < getdate(billed):
			frappe.throw(
				_("This contract is already billed up to {0}, after the last billable date {1} of this off-hire. "
					"Cancel the later billing schedule(s) and invoice(s), or raise a credit note and use an off-hire date on or after {0}.").format(
					frappe.format(billed, {"fieldtype": "Date"}), frappe.format(last, {"fieldtype": "Date"})
				),
				title=_("Period Already Billed"),
			)

	def validate_items(self):
		settings = get_settings()
		inspect = cint(settings.inspection_required)
		balance = ledger.get_site_balance(self.hire_contract)
		seen = set()
		self.total_returned_qty = self.total_lost_qty = 0
		for d in self.items:
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			if key in seen:
				frappe.throw(_("Row #{0}: {1} ({2}) is entered more than once").format(d.idx, d.item_code, d.ownership))
			seen.add(key)
			d.at_site_qty = balance.get(key, 0)
			moved = flt(d.returned_qty) + flt(d.lost_qty)
			if flt(d.returned_qty) < 0 or flt(d.lost_qty) < 0:
				frappe.throw(_("Row #{0}: quantities cannot be negative").format(d.idx))
			if moved > flt(d.at_site_qty) + 1e-6:
				frappe.throw(
					_("Row #{0}: {1} - returning {2} and writing off {3} but only {4} is at site").format(
						d.idx, frappe.bold(d.item_code), flt(d.returned_qty), flt(d.lost_qty), flt(d.at_site_qty)
					)
				)
			d.pending_qty = flt(d.at_site_qty) - moved
			if d.ownership == "Cross Hire":
				cho = frappe.db.get_value("Cross Hire Order", d.cross_hire_order, ["supplier", "receipt_warehouse"], as_dict=True)
				d.supplier = cho.supplier
				d.requires_inspection = inspect
				# supplier-owned material goes back to the cross hire warehouse, never into own-stock warehouses
				d.target_warehouse = cho.receipt_warehouse or settings.cross_hire_yard_warehouse
			else:
				d.cross_hire_order = None
				d.supplier = None
				profile = get_profile(d.item_code)
				d.requires_inspection = 1 if inspect and cint(profile.get("inspection_required", 1)) else 0
				if not d.target_warehouse:
					d.target_warehouse = settings.inspection_warehouse if d.requires_inspection else settings.rental_yard_warehouse
			if flt(d.returned_qty) and not d.target_warehouse:
				frappe.throw(_("Row #{0}: Return Warehouse is required. Check Rental Settings.").format(d.idx))
			self.total_returned_qty += flt(d.returned_qty)
			self.total_lost_qty += flt(d.lost_qty)
		if not (self.total_returned_qty or self.total_lost_qty):
			frappe.throw(_("Enter a returned or lost quantity on at least one row"))
		remaining = sum(balance.values()) - self.total_returned_qty - self.total_lost_qty
		self.off_hire_type = "Full" if remaining <= 1e-6 else "Partial"

	def on_submit(self):
		site = frappe.db.get_value(
			"Rental Site", self.rental_site, ["site_warehouse", "cross_hire_site_warehouse"], as_dict=True
		)

		def source(d):
			return site.cross_hire_site_warehouse if d.ownership == "Cross Hire" else site.site_warehouse

		returns = [
			{
				"item_code": d.item_code,
				"qty": d.returned_qty,
				"s_warehouse": source(d),
				"t_warehouse": d.target_warehouse,
				"zero_value": d.ownership == "Cross Hire",
				"batch_no": d.batch_no,
				"serial_no": d.serial_no,
			}
			for d in self.items
		]
		self.db_set("stock_entry", stock.make_stock_entry(self, "Material Transfer", returns, self.return_date))
		# lost material leaves stock here; the customer charge is raised by the Damage Settlement
		losses = [
			{"item_code": d.item_code, "qty": d.lost_qty, "s_warehouse": source(d), "zero_value": d.ownership == "Cross Hire"}
			for d in self.items
		]
		self.db_set(
			"loss_stock_entry",
			stock.make_stock_entry(self, "Material Issue", losses, self.return_date, remarks=f"Lost at site - {self.name}"),
		)

		billing_date = add_days(self.last_billable_date, 1)
		common = dict(
			posting_date=self.return_date,
			billing_date=billing_date,
			hire_contract=self.hire_contract,
			customer=self.customer,
			project=self.project,
			rental_site=self.rental_site,
		)
		cross_hire_orders = set()
		for d in self.items:
			row = dict(common, item_code=d.item_code, ownership=d.ownership, supplier=d.supplier,
				cross_hire_order=d.cross_hire_order, warehouse=source(d), voucher_detail_no=d.name)
			if flt(d.returned_qty):
				ledger.add_entry(self, position_type=ledger.AT_SITE, movement_type="Return", qty=-flt(d.returned_qty), **row)
			if flt(d.lost_qty):
				ledger.add_entry(self, position_type=ledger.AT_SITE, movement_type="Loss", qty=-flt(d.lost_qty), **row)
				if d.ownership == "Cross Hire":
					# lost supplier material also leaves our custody; the supplier's claim is booked by Purchase Invoice
					ledger.add_entry(self, position_type=ledger.CUSTODY, movement_type="Loss", qty=-flt(d.lost_qty), **row)
					cross_hire_orders.add(d.cross_hire_order)

		needs_inspection = any(cint(d.requires_inspection) and flt(d.returned_qty) for d in self.items)
		self.db_set(
			{
				"inspection_status": "Pending" if needs_inspection else "Not Required",
				"status": "Inspection Pending" if needs_inspection else "Completed",
			}
		)
		ledger.update_contract_progress(self.hire_contract)
		for cho in cross_hire_orders:
			ledger.update_cross_hire_progress(cho)
		set_request_reference(self)

	def on_cancel(self):
		set_request_reference(self, completed=False)
		billed = frappe.db.get_value("Hire Order Contract", self.hire_contract, "last_billed_upto")
		if billed and getdate(self.last_billable_date) < getdate(billed):
			frappe.throw(_("Cannot cancel: billing has been generated for periods after this off-hire. Cancel those billing schedules first."))
		stock.cancel_stock_entries(self)
		cross_hire_orders = {d.cross_hire_order for d in self.items if d.ownership == "Cross Hire" and flt(d.lost_qty)}
		ledger.delete_entries(self.doctype, self.name)
		self.db_set("status", "Cancelled")
		ledger.update_contract_progress(self.hire_contract)
		for cho in cross_hire_orders:
			ledger.update_cross_hire_progress(cho)


@frappe.whitelist()
def get_items_at_site(hire_contract: str):
	frappe.has_permission("Hire Order Contract", "read", hire_contract, throw=True)
	out = []
	for (item_code, ownership, cho), qty in sorted(ledger.get_site_balance(hire_contract).items()):
		if qty <= 0:
			continue
		item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
		out.append(
			{
				"item_code": item_code,
				"item_name": item.item_name,
				"uom": item.stock_uom,
				"ownership": ownership,
				"cross_hire_order": cho or None,
				"supplier": frappe.db.get_value("Cross Hire Order", cho, "supplier") if cho else None,
				"at_site_qty": qty,
				"pending_qty": qty,
			}
		)
	return out


@frappe.whitelist()
def make_inspection(source_name: str, target_doc=None):
	source = frappe.get_doc("Hire Off-Hire Note", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or source.inspection_status != "Pending":
		frappe.throw(_("This off-hire note has no inspection pending"))
	target = frappe.new_doc("Rental Return Inspection")
	target.update(
		{
			"company": source.company,
			"hire_off_hire_note": source.name,
			"hire_contract": source.hire_contract,
			"customer": source.customer,
			"customer_name": source.customer_name,
			"rental_site": source.rental_site,
			"inspection_date": nowdate(),
			"inspector": frappe.session.user,
		}
	)
	for d in source.items:
		if cint(d.requires_inspection) and flt(d.returned_qty):
			target.append(
				"items",
				{
					"item_code": d.item_code,
					"item_name": d.item_name,
					"uom": d.uom,
					"ownership": d.ownership,
					"cross_hire_order": d.cross_hire_order,
					"warehouse": d.target_warehouse,
					"returned_qty": d.returned_qty,
					"good_qty": d.returned_qty,
					"batch_no": d.batch_no,
				},
			)
	return target


@frappe.whitelist()
def make_damage_settlement(source_name: str, target_doc=None):
	"""Collect lost material from the off-hire note and damaged material from its inspection."""
	source = frappe.get_doc("Hire Off-Hire Note", source_name)
	source.check_permission("read")
	if source.docstatus != 1:
		frappe.throw(_("Submit the off-hire note first"))
	if source.inspection_status == "Pending":
		frappe.throw(_("Complete the return inspection first"))
	target = frappe.new_doc("Rental Damage Settlement")
	target.update(
		{
			"company": source.company,
			"hire_off_hire_note": source.name,
			"hire_contract": source.hire_contract,
			"customer": source.customer,
			"customer_name": source.customer_name,
			"posting_date": nowdate(),
		}
	)

	def add(d, classification, qty, rate_field):
		if flt(qty) <= 0:
			return
		target.append(
			"items",
			{
				"item_code": d.item_code,
				"item_name": d.item_name,
				"uom": d.uom,
				"ownership": d.ownership,
				"classification": classification,
				"qty": qty,
				"rate": flt(get_profile(d.item_code).get(rate_field)),
				"liability_percent": 100,
				"remarks": d.get("damage_notes"),
			},
		)

	for d in source.items:
		add(d, "Lost", d.lost_qty, "replacement_value")
	inspection = frappe.db.get_value("Rental Return Inspection", {"hire_off_hire_note": source.name, "docstatus": 1}, "name")
	if inspection:
		for d in frappe.get_doc("Rental Return Inspection", inspection).items:
			add(d, "Repairable", d.repairable_qty, "repair_charge")
			add(d, "Beyond Repair", d.damaged_qty, "replacement_value")
	if not target.items:
		frappe.throw(_("Nothing was lost or damaged on this off-hire"))
	return target
