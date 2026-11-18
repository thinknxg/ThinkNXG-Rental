import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from thinknxg_rental.services import damage_charges, excess
from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services import warehouses as rw
from thinknxg_rental.services.utils import get_profile, get_settings
from thinknxg_rental.thinknxg_rental.doctype.rental_portal_request.rental_portal_request import check_request_unused, set_request_reference


class HireOffHireNote(Document):
	def validate(self):
		self._contract = frappe.get_doc("Rental Contract", self.rental_contract)
		if self._contract.docstatus != 1 or self._contract.status in ("Completed", "Cancelled"):
			frappe.throw(_("Contract {0} is not live").format(self.rental_contract))
		for field in ("customer", "customer_name", "rental_site", "project"):
			self.set(field, self._contract.get(field))
		self.set_last_billable_date()
		check_request_unused(self)
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
		balance = ledger.get_site_balance(self.rental_contract)
		site = frappe.db.get_value("Rental Site", self.rental_site, ["site_warehouse", "cross_hire_site_warehouse"], as_dict=True) or frappe._dict()
		for d in self.items:
			if flt(d.returned_qty) < 0 or flt(d.lost_qty) < 0 or flt(d.excess_qty) < 0 or flt(d.get("received_qty")) < 0:
				frappe.throw(_("Row #{0}: quantities cannot be negative").format(d.idx))
			if d.ownership != "Cross Hire":
				d.cross_hire_order = None
		self.allocate_received()
		self.set_delivered_from()
		seen, moved_by_key = set(), {}
		self.total_returned_qty = self.total_lost_qty = 0
		excess_total = 0
		for d in self.items:
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			# one item can come back to several warehouses: one row per delivered-from and return warehouse
			row_key = key + (d.delivered_from or "", d.target_warehouse or "", d.return_to_warehouse or "")
			if row_key in seen:
				frappe.throw(_("Row #{0}: {1} ({2}) is entered more than once for the same warehouses").format(d.idx, d.item_code, d.ownership))
			seen.add(row_key)
			moved_by_key[key] = moved_by_key.get(key, 0) + flt(d.returned_qty) + flt(d.lost_qty)
			prefix = _("Row #{0}: ").format(d.idx)
			d.site_warehouse = site.cross_hire_site_warehouse if d.ownership == "Cross Hire" else site.site_warehouse
			if d.ownership == "Cross Hire":
				cho = frappe.db.get_value("Cross Hire Order", d.cross_hire_order, ["supplier", "receipt_warehouse"], as_dict=True)
				if not cho:
					frappe.throw(prefix + _("Cross Hire Order is required for cross-hired material"))
				d.supplier = cho.supplier
				d.requires_inspection = inspect
				d.return_to_warehouse = None
				# supplier-owned material goes back to a cross hire warehouse, never into own-stock warehouses
				d.target_warehouse = d.target_warehouse or cho.receipt_warehouse or rw.default_cross_hire_warehouse()
				if flt(d.returned_qty):
					rw.validate_cross_hire(d.target_warehouse, prefix, allowed=[cho.receipt_warehouse], company=self.company)
			else:
				d.supplier = None
				profile = get_profile(d.item_code)
				d.requires_inspection = 1 if inspect and cint(profile.get("inspection_required", 1)) else 0
				self.set_own_return_warehouses(d, settings, prefix)
			if flt(d.returned_qty) and not d.target_warehouse:
				frappe.throw(_("Row #{0}: Return To (warehouse) is required. Check Rental Settings.").format(d.idx))
			d.location = rw.location_of(d.return_to_warehouse or d.target_warehouse)
			if d.delivered_from and not d.delivery_order:
				d.delivery_order = ledger.get_last_delivery(self.rental_contract, d.item_code, d.delivered_from)
			self.total_returned_qty += flt(d.returned_qty)
			self.total_lost_qty += flt(d.lost_qty)
			if flt(d.excess_qty) > 0 and d.ownership == "Cross Hire":
				frappe.throw(_("Row #{0}: Excess Qty is only for own stock").format(d.idx))
			self.set_excess(d, settings, prefix)
			excess_total += flt(d.excess_qty)
		# what comes back (returned + lost) is capped by what is at site, over all rows of the item
		for d in self.items:
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			d.at_site_qty = balance.get(key, 0)
			if moved_by_key[key] > flt(d.at_site_qty) + 1e-6:
				frappe.throw(
					_("Row #{0}: {1} - returning and writing off {2} over all its rows but only {3} is at site").format(
						d.idx, frappe.bold(d.item_code), moved_by_key[key], flt(d.at_site_qty)
					)
				)
			d.pending_qty = flt(d.at_site_qty) - moved_by_key[key]
		if not (self.total_returned_qty or self.total_lost_qty or excess_total):
			frappe.throw(_("Enter a returned or lost quantity on at least one row"))
		if excess_total and any(flt(d.excess_qty) > 0 and not d.excess_warehouse for d in self.items):
			frappe.throw(_("Set the Excess Warehouse in Rental Settings first"))
		self.total_excess_qty = excess_total
		remaining = sum(balance.values()) - self.total_returned_qty - self.total_lost_qty
		self.off_hire_type = "Full" if remaining <= 1e-6 else "Partial"

	def allocate_received(self):
		"""Rows with a Received quantity (everything that physically came back): Returned is what is at
		site, up to the quantity received; the rest is Excess. Capacity is shared over the rows of the same
		item, and a row with Delivered From set is capped by what is at site from that warehouse. Lost
		units and rows entered without a Received quantity are counted first. Cross-hired rows have no
		excess: their Received quantity is the Returned quantity (checked against the site as usual)."""
		if self.docstatus != 0 or not any(flt(d.get("received_qty")) > 0 for d in self.items):
			return
		by_origin = ledger.get_site_balance_by_origin(self.rental_contract)
		key_cap, origin_cap = {}, dict(by_origin)
		for k, q in by_origin.items():
			key_cap[k[:3]] = key_cap.get(k[:3], 0) + q
		for d in self.items:
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			used = flt(d.lost_qty) + (0 if flt(d.get("received_qty")) > 0 else flt(d.returned_qty))
			key_cap[key] = key_cap.get(key, 0) - used
			if d.delivered_from:
				okey = key + (d.delivered_from,)
				origin_cap[okey] = origin_cap.get(okey, 0) - used
		for d in sorted((d for d in self.items if flt(d.get("received_qty")) > 0), key=lambda d: (0 if d.delivered_from else 1, d.idx)):
			received = flt(d.received_qty)
			if d.ownership == "Cross Hire":
				d.returned_qty, d.excess_qty = received, 0
				continue
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			cap = key_cap.get(key, 0)
			if d.delivered_from:
				cap = min(cap, origin_cap.get(key + (d.delivered_from,), 0))
			returned = max(min(received, cap), 0)
			d.returned_qty, d.excess_qty = returned, received - returned
			key_cap[key] = key_cap.get(key, 0) - returned
			if d.delivered_from:
				origin_cap[key + (d.delivered_from,)] -= returned

	def set_excess(self, d, settings, prefix):
		"""Classify a row's excess and check where it goes."""
		d.is_excess = 1 if flt(d.excess_qty) > 0 else 0
		if not d.is_excess:
			d.excess_category = None
			d.excess_warehouse = None
			return
		d.excess_category = excess.excess_category(self.rental_contract, d.item_code)
		d.excess_warehouse = d.excess_warehouse or settings.get("excess_warehouse")
		if not d.excess_warehouse:
			return
		if (d.excess_warehouse in rw.get_warehouses(rw.OWN, active_only=False) or d.excess_warehouse in rw.get_warehouses(rw.CROSS_HIRE, active_only=False)
				or rw.is_site_warehouse(d.excess_warehouse)):
			frappe.throw(prefix + _("{0} is a rental, cross hire or site warehouse. Excess material is kept apart, in an excess warehouse.").format(
				frappe.bold(d.excess_warehouse)), title=_("Excess Warehouse"))
		if frappe.db.get_value("Warehouse", d.excess_warehouse, "company") != self.company:
			frappe.throw(prefix + _("{0} belongs to another company").format(d.excess_warehouse))

	def set_own_return_warehouses(self, d, settings, prefix):
		"""Own material: Return To is the warehouse where it is moved now - an own rental warehouse, or the
		inspection warehouse; Good Stock Returns To is the own warehouse it ends up in. Material that
		needs inspection always goes to the inspection warehouse first: a rental warehouse picked as the
		Return To becomes its Good Stock Returns To."""
		inspection = settings.inspection_warehouse
		if d.target_warehouse and d.target_warehouse != inspection and cint(d.requires_inspection):
			d.return_to_warehouse = d.return_to_warehouse or d.target_warehouse
			d.target_warehouse = inspection
		if not d.return_to_warehouse:
			if d.target_warehouse and d.target_warehouse != inspection:
				d.return_to_warehouse = d.target_warehouse
			elif d.delivered_from and rw.is_own(d.delivered_from, active_only=True):
				d.return_to_warehouse = d.delivered_from  # back where it came from
			else:
				d.return_to_warehouse = rw.default_own_warehouse()
		if not d.target_warehouse:
			d.target_warehouse = inspection if cint(d.requires_inspection) else d.return_to_warehouse
		if not (flt(d.returned_qty) or flt(d.excess_qty)):
			return
		if d.target_warehouse == inspection and inspection:
			if not cint(d.requires_inspection):
				d.requires_inspection = 1  # sent to inspection by hand
		else:
			rw.validate_own(d.target_warehouse, prefix, company=self.company)
		if d.return_to_warehouse:
			rw.validate_own(d.return_to_warehouse, prefix + _("Good Stock Returns To: "), company=self.company)
		if d.target_warehouse == d.site_warehouse:
			frappe.throw(prefix + _("own material cannot be returned into the site warehouse"))

	def set_delivered_from(self):
		"""Fill Delivered From from what is at site, splitting a row over the warehouses its material was
		dispatched from (largest first). A Delivered From chosen by hand is checked against what is at
		site from that warehouse."""
		by_origin = ledger.get_site_balance_by_origin(self.rental_contract)
		left = dict(by_origin)
		for d in self.items:
			if d.delivered_from:
				key = (d.item_code, d.ownership, d.cross_hire_order or "", d.delivered_from)
				left[key] = left.get(key, 0) - flt(d.returned_qty) - flt(d.lost_qty)
				if left[key] < -1e-6:
					frappe.throw(
						_("Row #{0}: {1} - only {2} delivered from {3} is at site").format(
							d.idx, frappe.bold(d.item_code), flt(by_origin.get(key)), d.delivered_from
						)
					)
		if self.docstatus != 0:
			return
		order = []
		for d in list(self.items):
			if d.delivered_from:
				order.append(d)
				continue
			origins = sorted(
				[(q, k[3]) for k, q in left.items() if k[:3] == (d.item_code, d.ownership, d.cross_hire_order or "") and q > 1e-9],
				key=lambda o: (-o[0], o[1]),
			)
			returned, lost, first = flt(d.returned_qty), flt(d.lost_qty), True
			for qty, origin in origins:
				if returned + lost <= 1e-9:
					break
				take_r = min(returned, qty)
				take_l = min(lost, qty - take_r)
				if take_r + take_l <= 1e-9:
					continue
				row = d if first else self._copy_row(d)
				row.delivered_from = origin or None
				row.returned_qty, row.lost_qty = take_r, take_l
				if flt(d.get("received_qty")) > 0:
					# what came back stays with the row it is on: the excess with the first row
					row.received_qty = take_r + (flt(d.excess_qty) if first else 0)
				if not first:
					row.excess_qty = 0
				left[(d.item_code, d.ownership, d.cross_hire_order or "", origin)] -= take_r + take_l
				returned -= take_r
				lost -= take_l
				first = False
				order.append(row)
			if first:
				order.append(d)
			elif returned + lost > 1e-9:  # more than is at site: the at-site check reports it
				d.returned_qty, d.lost_qty = flt(d.returned_qty) + returned, flt(d.lost_qty) + lost
		self.items = order
		for i, d in enumerate(self.items, 1):
			d.idx = i

	def _copy_row(self, d):
		fields = ("item_code", "item_name", "uom", "ownership", "cross_hire_order", "supplier", "target_warehouse",
			"return_to_warehouse", "batch_no", "serial_no", "remarks", "excess_warehouse")
		row = self.append("items", {k: d.get(k) for k in fields})
		self.items.remove(row)
		return row

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
		stock_entry = stock.make_stock_entry(self, "Material Transfer", returns, self.return_date)
		self.db_set("stock_entry", stock_entry)
		for d in self.items:
			if flt(d.returned_qty) and source(d) != d.target_warehouse:
				d.db_set("stock_entry", stock_entry, update_modified=False)
		# lost material leaves stock here; the customer charge is raised by the Damage Settlement
		losses = [
			{"item_code": d.item_code, "qty": d.lost_qty, "s_warehouse": source(d), "zero_value": d.ownership == "Cross Hire"}
			for d in self.items
		]
		self.db_set(
			"loss_stock_entry",
			stock.make_stock_entry(self, "Material Issue", losses, self.return_date, remarks=f"Lost at site - {self.name}"),
		)

		# material received over and above what is at site goes into the excess warehouse, at zero value, and
		# each row of it gets an Excess Material Register (services/excess.py)
		received = [{"item_code": d.item_code, "qty": d.excess_qty, "t_warehouse": d.excess_warehouse or get_settings().excess_warehouse,
			"zero_value": True, "batch_no": d.get("excess_batch_no"), "serial_no": d.get("excess_serial_no")}
			for d in self.items if flt(d.excess_qty) > 0]
		if received:
			excess_entry = stock.make_stock_entry(self, "Material Receipt", received, self.return_date, remarks=f"Excess received - {self.name}")
			self.db_set("excess_stock_entry", excess_entry)
			excess.make_registers(self, excess_entry)

		billing_date = add_days(self.last_billable_date, 1)
		common = dict(
			posting_date=self.return_date,
			billing_date=billing_date,
			rental_contract=self.rental_contract,
			customer=self.customer,
			project=self.project,
			rental_site=self.rental_site,
		)
		cross_hire_orders = set()
		for d in self.items:
			row = dict(common, item_code=d.item_code, ownership=d.ownership, supplier=d.supplier,
				cross_hire_order=d.cross_hire_order, warehouse=source(d), origin_warehouse=d.delivered_from,
				source_warehouse=source(d), voucher_detail_no=d.name)
			if flt(d.returned_qty):
				ledger.add_entry(self, position_type=ledger.AT_SITE, movement_type="Return", qty=-flt(d.returned_qty),
					target_warehouse=d.target_warehouse, stock_entry=d.get("stock_entry"), **row)
			# custody is held per cross hire warehouse: the warehouse the material was dispatched from
			origin = d.delivered_from or (d.ownership == "Cross Hire" and frappe.db.get_value("Cross Hire Order", d.cross_hire_order, "receipt_warehouse"))
			if d.ownership == "Cross Hire" and flt(d.returned_qty) and origin and d.target_warehouse != origin:
				# came back to another cross hire warehouse: custody moves with it, billing does not change
				move = dict(row, position_type=ledger.CUSTODY, movement_type="Transfer", billing_date=self.return_date,
					source_warehouse=origin, target_warehouse=d.target_warehouse, stock_entry=d.get("stock_entry"))
				ledger.add_entry(self, qty=-flt(d.returned_qty), **dict(move, warehouse=origin))
				ledger.add_entry(self, qty=flt(d.returned_qty), **dict(move, warehouse=d.target_warehouse))
			if flt(d.lost_qty):
				ledger.add_entry(self, position_type=ledger.AT_SITE, movement_type="Loss", qty=-flt(d.lost_qty), **row)
				if d.ownership == "Cross Hire":
					# lost supplier material also leaves our custody; the supplier's claim is booked by Purchase Invoice
					ledger.add_entry(self, position_type=ledger.CUSTODY, movement_type="Loss", qty=-flt(d.lost_qty),
						**dict(row, warehouse=origin or row["warehouse"]))
					cross_hire_orders.add(d.cross_hire_order)

		needs_inspection = any(cint(d.requires_inspection) and flt(d.returned_qty) for d in self.items)
		self.db_set(
			{
				"inspection_status": "Pending" if needs_inspection else "Not Required",
				"status": "Inspection Pending" if needs_inspection else "Completed",
			}
		)
		ledger.update_contract_progress(self.rental_contract)
		for cho in cross_hire_orders:
			ledger.update_cross_hire_progress(cho)
		set_request_reference(self)

	def before_cancel(self):
		excess.check_note_can_cancel(self)

	def on_cancel(self):
		set_request_reference(self, completed=False)
		billed = frappe.db.get_value("Rental Contract", self.rental_contract, "last_billed_upto")
		if billed and getdate(self.last_billable_date) < getdate(billed):
			frappe.throw(_("Cannot cancel: billing has been generated for periods after this off-hire. Cancel those billing schedules first."))
		stock.cancel_stock_entries(self)
		cross_hire_orders = {d.cross_hire_order for d in self.items if d.ownership == "Cross Hire" and flt(d.lost_qty)}
		ledger.delete_entries(self.doctype, self.name)
		excess.cancel_registers(self)
		self.db_set("status", "Cancelled")
		ledger.update_contract_progress(self.rental_contract)
		for cho in cross_hire_orders:
			ledger.update_cross_hire_progress(cho)


@frappe.whitelist()
def get_items_at_site(rental_contract: str):
	"""What is at site, one row per item, ownership, cross hire order and the warehouse it was
	delivered from; own rows suggest going back to that warehouse."""
	frappe.has_permission("Rental Contract", "read", rental_contract, throw=True)
	out = []
	for (item_code, ownership, cho, origin), qty in sorted(ledger.get_site_balance_by_origin(rental_contract).items()):
		if qty <= 0:
			continue
		item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
		row = {
			"item_code": item_code,
			"item_name": item.item_name,
			"uom": item.stock_uom,
			"ownership": ownership,
			"cross_hire_order": cho or None,
			"supplier": frappe.db.get_value("Cross Hire Order", cho, "supplier") if cho else None,
			"at_site_qty": qty,
			"pending_qty": qty,
			"delivered_from": origin or None,
			"delivery_order": ledger.get_last_delivery(rental_contract, item_code, origin or None),
		}
		if ownership == "Own" and origin and rw.is_own(origin, active_only=True):
			row["return_to_warehouse"] = origin
		out.append(row)
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
			"rental_contract": source.rental_contract,
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
					"good_warehouse": d.get("return_to_warehouse") if d.ownership != "Cross Hire" else None,
					"delivered_from": d.get("delivered_from"),
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
			"rental_contract": source.rental_contract,
			"customer": source.customer,
			"customer_name": source.customer_name,
			"posting_date": nowdate(),
		}
	)

	# rates are the damage and loss charges agreed on the Rental Contract (services/damage_charges.py),
	# never the Rental Item Profile's current values
	agreed = damage_charges.contract_rows(source.rental_contract)

	def add(d, classification, qty):
		if flt(qty) <= 0:
			return
		rate, rate_source = damage_charges.settlement_rate(source.rental_contract, agreed.get(d.item_code), classification)
		target.append(
			"items",
			{
				"item_code": d.item_code,
				"item_name": d.item_name,
				"uom": d.uom,
				"ownership": d.ownership,
				"classification": classification,
				"qty": qty,
				"rate": rate,
				"rate_source": rate_source,
				"liability_percent": 100,
				"remarks": d.get("damage_notes"),
			},
		)

	for d in source.items:
		add(d, "Lost", d.lost_qty)
	inspection = frappe.db.get_value("Rental Return Inspection", {"hire_off_hire_note": source.name, "docstatus": 1}, "name")
	if inspection:
		for d in frappe.get_doc("Rental Return Inspection", inspection).items:
			add(d, "Repairable", d.repairable_qty)
			add(d, "Beyond Repair", d.damaged_qty)
	if not target.items:
		frappe.throw(_("Nothing was lost or damaged on this off-hire"))
	return target
