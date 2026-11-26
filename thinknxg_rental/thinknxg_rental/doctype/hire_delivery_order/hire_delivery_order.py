import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services import warehouses as rw
from thinknxg_rental.services.utils import (
	get_available_qty,
	get_reserved_for_others,
	get_bin_qty,
	get_contract_for_source,
	get_contract_source,
	get_profile,
	get_settings,
)


class HireDeliveryOrder(Document):
	def set_missing_values(self):
		# the delivery can be started from the rental source; the Rental Contract is then looked up
		if not self.rental_contract and self.source_type and self.source_document:
			self.rental_contract = get_contract_for_source(self.source_type, self.source_document)
			if not self.rental_contract:
				frappe.throw(
					_("{0} {1} has no submitted Rental Contract yet. Create the Rental Contract first.").format(
						self.source_type, self.source_document
					)
				)
		if not self.rental_contract:
			frappe.throw(_("Select a Rental Contract, or a Hire Order / Hire Order Contract as the rental source"))
		contract = frappe.db.get_value(
			"Rental Contract",
			self.rental_contract,
			["source_type", "source_document", "customer", "customer_name", "rental_site", "project", "company"],
			as_dict=True,
		)
		if contract:
			self.update({k: v for k, v in contract.items() if k != "company"})
			self.company = self.company or contract.company

	def validate(self):
		self.set_missing_values()
		self._contract = frappe.get_doc("Rental Contract", self.rental_contract)
		if self._contract.docstatus != 1 or self._contract.status in ("Completed", "Cancelled"):
			frappe.throw(_("Contract {0} is not live").format(self.rental_contract))
		if self._contract.last_billed_upto and getdate(self.posting_date) <= getdate(self._contract.last_billed_upto):
			frappe.throw(
				_("Dispatch Date must be after {0}, the date this contract is already billed up to.").format(
					frappe.format(self._contract.last_billed_upto, {"fieldtype": "Date"})
				)
			)
		self.set_reserved_warehouses()
		self.validate_items()
		self.validate_reservation()

	def set_reserved_warehouses(self):
		"""Own stock leaves from the warehouses it was reserved in. A row without a warehouse is split
		over the item's reservation allocations (the named reservation, else the contract's reservations,
		oldest first); what no allocation covers leaves from the default own rental warehouse. A row
		with a warehouse keeps it: the warehouse is never changed behind the user's back."""
		from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
			get_reservation_allocations,
			get_reserved_stock,
		)

		if self.docstatus != 0:
			return
		if self.rental_material_reservation:
			allocations = [(i, w, q) for (i, w), q in get_reservation_allocations(self.rental_material_reservation).items() if q > 0]
		else:
			allocations = list(get_reserved_stock(self.rental_contract))
		left = {}
		for item_code, warehouse, qty in allocations:
			left.setdefault(item_code, []).append([warehouse, qty])
		for d in self.items:  # rows that name their warehouse use up its allocation first
			if d.ownership != "Cross Hire" and d.source_warehouse and not cint(d.additional_item):
				for alloc in left.get(d.item_code, []):
					if alloc[0] == d.source_warehouse:
						alloc[1] -= flt(d.qty)
		order = []
		default = rw.default_own_warehouse()
		for d in list(self.items):
			if cint(d.additional_item) and d.ownership != "Cross Hire" and not d.source_warehouse:
				# additional material was never reserved: it leaves from the default own rental warehouse
				d.source_warehouse = default
			if d.ownership == "Cross Hire" or d.source_warehouse:
				order.append(d)
				continue
			remaining, first = flt(d.qty), True
			for alloc in left.get(d.item_code, []):
				if remaining <= 1e-9:
					break
				take = min(remaining, alloc[1])
				if take <= 1e-9:
					continue
				row = d if first else self._copy_row(d)
				row.source_warehouse, row.qty = alloc[0], take
				alloc[1] -= take
				remaining -= take
				first = False
				order.append(row)
			if remaining > 1e-9:
				if first:
					d.source_warehouse = default
					order.append(d)
				else:
					# validate_reservation still holds a named reservation to its balance
					row = self._copy_row(d)
					row.source_warehouse, row.qty = default, remaining
					order.append(row)
		self.items = order
		for i, d in enumerate(self.items, 1):
			d.idx = i

	def _copy_row(self, d):
		row = self.append("items", {k: d.get(k) for k in ("item_code", "item_name", "uom", "ownership", "batch_no", "serial_no", "remarks", "additional_item", "job_type")})
		self.items.remove(row)
		return row

	def validate_reservation(self):
		"""When a reservation is named, own-stock lines are held to its balance in each warehouse."""
		for d in self.items:
			d.reservation_balance = 0
		if not self.rental_material_reservation:
			return
		from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
			get_contract_reservations,
			get_reservation_balance,
		)

		if self.rental_material_reservation not in get_contract_reservations(self.rental_contract):
			frappe.throw(
				_("Reservation {0} is not a submitted reservation of contract {1}").format(
					self.rental_material_reservation, self.rental_contract
				)
			)
		if frappe.db.get_value("Rental Material Reservation", self.rental_material_reservation, "status") == "Released":
			frappe.throw(_("Reservation {0} has been released").format(self.rental_material_reservation))
		balance = get_reservation_balance(self.rental_material_reservation)
		reserved_in = {}
		for item_code, warehouse in balance:
			reserved_in.setdefault(item_code, []).append(warehouse)
		wanted = {}
		for d in self.items:
			if d.ownership != "Own" or cint(d.additional_item):  # additional material is not part of any reservation
				continue
			key = (d.item_code, d.source_warehouse)
			if d.item_code in reserved_in and d.source_warehouse not in reserved_in[d.item_code]:
				frappe.throw(
					_("Row #{0}: {1} is reserved in {2} on reservation {3}, not in {4}. "
						"Use that warehouse, or clear the reservation field.").format(
						d.idx, frappe.bold(d.item_code), ", ".join(reserved_in[d.item_code]), self.rental_material_reservation, d.source_warehouse
					)
				)
			d.reservation_balance = balance.get(key, 0)
			wanted[key] = wanted.get(key, 0) + flt(d.qty)
		for (item_code, warehouse), qty in wanted.items():
			if qty > balance.get((item_code, warehouse), 0) + 1e-6:
				frappe.throw(
					_("{0}: dispatching {1} of own stock from {2} but reservation {3} has a balance of {4} there. "
						"Reserve more, use cross-hired stock, or clear the reservation field.").format(
						frappe.bold(item_code), qty, warehouse, self.rental_material_reservation, balance.get((item_code, warehouse), 0)
					)
				)

	def validate_items(self):
		site = frappe.db.get_value(
			"Rental Site", self.rental_site, ["site_warehouse", "cross_hire_site_warehouse"], as_dict=True
		)
		contract_items = {d.item_code: d for d in self._contract.items}
		job_types = get_contract_job_types(self.rental_contract)
		reserved_warehouses = self._reserved_warehouses()
		per_item, per_cho, per_bin, per_custody = {}, {}, {}, {}
		self._additional = {}
		self.total_qty = self.total_weight = 0
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
			row = contract_items.get(d.item_code)
			# material that is not on the contract is additional by definition
			d.additional_item = 1 if (cint(d.additional_item) or not row) else 0
			if d.additional_item:
				self.validate_additional_item(d, job_types)
				d.job_type = d.job_type or None
				self._additional[d.item_code] = self._additional.get(d.item_code, 0) + flt(d.qty)
				d.contract_qty = row.qty if row else 0
				d.previously_delivered = row.dispatched_qty if row else 0
				d.balance_to_deliver = 0
			else:
				if not row:
					frappe.throw(
						_("Row #{0}: {1} is not on contract {2}. Tick Additional Item to add it to the contract with this delivery.").format(
							d.idx, d.item_code, self.rental_contract)
					)
				d.job_type = None
				d.contract_qty = row.qty
				d.previously_delivered = row.dispatched_qty
				d.balance_to_deliver = flt(row.qty) - flt(d.previously_delivered)
			prefix = _("Row #{0}: ").format(d.idx)
			if d.ownership == "Cross Hire":
				if not d.cross_hire_order:
					frappe.throw(_("Row #{0}: Cross Hire Order is required for cross-hired material").format(d.idx))
				cho = frappe.db.get_value(
					"Cross Hire Order", d.cross_hire_order, ["docstatus", "supplier", "receipt_warehouse", "status"], as_dict=True
				)
				if cho.docstatus != 1 or cho.status == "Completed":
					frappe.throw(_("Row #{0}: Cross Hire Order {1} is not open").format(d.idx, d.cross_hire_order))
				d.supplier = cho.supplier
				d.source_warehouse = d.source_warehouse or cho.receipt_warehouse or rw.default_cross_hire_warehouse()
				d.target_warehouse = site.cross_hire_site_warehouse
				# supplier material leaves only from a cross hire warehouse (or the site it was received at)
				rw.validate_cross_hire(d.source_warehouse, prefix, allowed=[cho.receipt_warehouse, site.cross_hire_site_warehouse],
					allow_inactive=True, company=self.company)
				key = (d.cross_hire_order, d.item_code)
				per_cho[key] = per_cho.get(key, 0) + flt(d.qty)
				if d.source_warehouse != d.target_warehouse:
					key = (d.cross_hire_order, d.item_code, d.source_warehouse)
					per_custody[key] = per_custody.get(key, 0) + flt(d.qty)
			else:
				d.cross_hire_order = None
				d.supplier = None
				d.source_warehouse = d.source_warehouse or rw.default_own_warehouse()
				d.target_warehouse = site.site_warehouse
				# own stock leaves only from an own rental warehouse; a warehouse retired after the
				# reservation was made still delivers what is reserved in it
				if d.source_warehouse:
					rw.validate_own(d.source_warehouse, prefix, company=self.company,
						allow_inactive=(d.item_code, d.source_warehouse) in reserved_warehouses)
			if not d.source_warehouse or not d.target_warehouse:
				frappe.throw(_("Row #{0}: source and site warehouse are required. Check Rental Settings and the Rental Site.").format(d.idx))
			if d.ownership == "Own" and d.source_warehouse == d.target_warehouse:
				frappe.throw(_("Row #{0}: own material cannot be dispatched from the site warehouse itself").format(d.idx))
			d.location = rw.location_of(d.source_warehouse)
			if d.source_warehouse != d.target_warehouse:
				key = (d.item_code, d.source_warehouse)
				per_bin[key] = per_bin.get(key, 0) + flt(d.qty)
			d.weight = flt(d.qty) * flt(get_profile(d.item_code).get("weight_per_unit"))
			if not d.additional_item:
				per_item[d.item_code] = per_item.get(d.item_code, 0) + flt(d.qty)
			self.total_qty += flt(d.qty)
			self.total_weight += flt(d.weight)

		for item_code, qty in per_item.items():
			row = contract_items[item_code]
			balance = flt(row.qty) - flt(row.dispatched_qty)
			if qty > balance + 1e-6:
				frappe.throw(
					_("{0}: dispatching {1} but only {2} remains on the contract. Increase the contracted quantity first, "
						"or tick Additional Item on the extra quantity.").format(
						frappe.bold(item_code), qty, balance
					)
				)
		for (cho, item_code), qty in per_cho.items():
			free = ledger.get_cross_hire_undelivered(cho, item_code)
			if qty > free + 1e-6:
				frappe.throw(
					_("{0}: only {1} received and undelivered on Cross Hire Order {2} (dispatching {3})").format(
						frappe.bold(item_code), free, cho, qty
					)
				)
		if per_custody:
			# the order's own material must be in that cross hire warehouse: another supplier's is not taken
			from thinknxg_rental.services.inventory import in_custody_not_at_site

			for (cho, item_code, warehouse), qty in per_custody.items():
				held = flt(in_custody_not_at_site([item_code], cho).get((cho, item_code, warehouse)))
				if qty > held + 1e-6:
					frappe.throw(
						_("{0}: only {1} of Cross Hire Order {2} is in {3} (dispatching {4})").format(
							frappe.bold(item_code), held, cho, warehouse, qty
						)
					)
		self._per_bin = per_bin
		self.validate_stock(per_bin)

	def validate_additional_item(self, d, job_types):
		item = frappe.db.get_value("Item", d.item_code, ["is_stock_item", "disabled", "item_name"], as_dict=True)
		if not item or not item.is_stock_item:
			frappe.throw(_("Row #{0}: {1} is not a stock item, so it cannot be hired out").format(d.idx, d.item_code))
		if item.disabled:
			frappe.throw(_("Row #{0}: {1} is disabled").format(d.idx, d.item_code))
		# a job type contract allocates its material to job types: the additional item names the one it is for
		if not job_types:
			d.job_type = None
			return
		if not d.job_type and len(job_types) == 1:
			d.job_type = job_types[0]
		if not d.job_type:
			frappe.throw(_("Row #{0}: select the Job Type that {1} is for").format(d.idx, frappe.bold(d.item_code)))
		if d.job_type not in job_types:
			frappe.throw(_("Row #{0}: {1} is not a job type of this contract ({2})").format(d.idx, frappe.bold(d.job_type), ", ".join(job_types)))

	def add_to_contract(self):
		"""Additional material becomes part of the live contract: a new contract row, or more quantity on the
		row it extends. The original rows and quantities are never rewritten; Additional Qty keeps the part
		that came from deliveries. From here billing, material at site, off-hire, inspection and closure
		see it like any contracted item."""
		if not any(cint(d.additional_item) for d in self.items):
			return
		contract = frappe.get_doc("Rental Contract", self.rental_contract)
		wanted, job_type = {}, {}
		for d in self.items:
			if cint(d.additional_item):
				wanted[d.item_code] = wanted.get(d.item_code, 0) + flt(d.qty)
				job_type.setdefault(d.item_code, d.job_type)
		rows = {r.item_code: r for r in contract.items}
		for item_code, qty in wanted.items():
			row = rows.get(item_code)
			if row:
				row.qty = flt(row.qty) + qty
				row.additional_qty = flt(row.additional_qty) + qty
				row.job_type = row.job_type or job_type[item_code]
			else:
				contract.append("items", {"item_code": item_code, "qty": qty, "additional_qty": qty, "is_additional": 1,
					"added_by_delivery": self.name, "rate_basis": "Monthly", "job_type": job_type[item_code]})
		contract.flags.ignore_permissions = True
		contract.save()
		self._contract = contract

	def take_from_contract(self):
		"""Cancelling the delivery takes its additional quantity off the contract again (a row that exists only
		because of deliveries goes once none is left)."""
		taken = {}
		for d in self.items:
			if cint(d.additional_item):
				taken[d.item_code] = taken.get(d.item_code, 0) + flt(d.qty)
		if not taken:
			return
		ledger.update_contract_progress(self.rental_contract)  # the cancelled dispatch is no longer counted
		contract = frappe.get_doc("Rental Contract", self.rental_contract)
		for row in list(contract.items):
			qty = taken.get(row.item_code)
			if not qty:
				continue
			row.additional_qty = max(flt(row.additional_qty) - qty, 0)
			row.qty = max(flt(row.qty) - qty, 0)
			if cint(row.is_additional) and row.additional_qty <= 1e-9:
				contract.remove(row)
		for i, row in enumerate(contract.items, 1):
			row.idx = i
		contract.flags.ignore_permissions = True
		contract.save()

	def _reserved_warehouses(self):
		from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
			get_reservation_allocations,
			get_reserved_stock,
		)

		if self.rental_material_reservation:
			return set(get_reservation_allocations(self.rental_material_reservation, balance=False))
		return {(i, w) for i, w, _q in get_reserved_stock(self.rental_contract)}

	def validate_stock(self, per_bin, lock=False):
		"""Each source warehouse must hold what leaves it."""
		if lock:
			rw.lock_bins(per_bin)
		for (item_code, warehouse), qty in per_bin.items():
			in_stock = get_bin_qty(item_code, warehouse, for_update=lock)
			if qty > in_stock + 1e-6:
				frappe.throw(
					_("{0}: dispatching {1} from {2} but only {3} is in stock there").format(frappe.bold(item_code), qty, warehouse, in_stock),
					title=_("Not Enough Stock"),
				)

	def _submit(self):
		# stock rows first, before this document is locked (see Rental Material Reservation._submit)
		rw.lock_bins((d.item_code, d.source_warehouse) for d in self.items if d.source_warehouse and d.source_warehouse != d.target_warehouse)
		return super()._submit()

	def before_submit(self):
		# lock the stock rows this delivery draws from, so a concurrent reservation or delivery waits
		self.validate_stock(getattr(self, "_per_bin", None) or {}, lock=True)
		settings = get_settings()
		if not cint(settings.enforce_reservation_on_dispatch):
			return
		needed = {}
		for d in self.items:
			if d.ownership == "Own":
				key = (d.item_code, d.source_warehouse)
				needed[key] = needed.get(key, 0) + flt(d.qty)
		for (item_code, warehouse), qty in needed.items():
			available = get_bin_qty(item_code, warehouse, for_update=True) - get_reserved_for_others(
				item_code, warehouse, self.rental_contract, get_contract_source(self.rental_contract), for_update=True
			)
			if qty > available + 1e-6:
				frappe.throw(
					_("{0}: {1} required from {2} but only {3} is free ({4} in stock, the rest is reserved for other contracts).").format(
						frappe.bold(item_code), qty, warehouse, max(available, 0), get_bin_qty(item_code, warehouse)
					),
					title=_("Reserved for Other Contracts"),
				)

	def on_submit(self):
		rows = [
			{
				"item_code": d.item_code,
				"qty": d.qty,
				"s_warehouse": d.source_warehouse,
				"t_warehouse": d.target_warehouse,
				"zero_value": d.ownership == "Cross Hire",
				"batch_no": d.batch_no,
				"serial_no": d.serial_no,
			}
			for d in self.items
		]
		# cross hire delivered by the supplier straight to site is already in the site warehouse: no transfer
		stock_entry = stock.make_stock_entry(self, "Material Transfer", rows, self.posting_date)
		self.db_set("stock_entry", stock_entry)
		for d in self.items:
			ledger.add_entry(
				self,
				posting_date=self.posting_date,
				billing_date=self.posting_date,
				position_type=ledger.AT_SITE,
				movement_type="Dispatch",
				item_code=d.item_code,
				qty=flt(d.qty),
				ownership=d.ownership,
				supplier=d.supplier,
				cross_hire_order=d.cross_hire_order,
				rental_contract=self.rental_contract,
				customer=self.customer,
				project=self.project,
				rental_site=self.rental_site,
				warehouse=d.target_warehouse,
				origin_warehouse=d.source_warehouse,
				source_warehouse=d.source_warehouse,
				target_warehouse=d.target_warehouse,
				stock_entry=stock_entry if d.source_warehouse != d.target_warehouse else None,
				voucher_detail_no=d.name,
			)
		self.add_to_contract()
		self.update_related()

	def on_cancel(self):
		balance = ledger.get_site_balance(self.rental_contract)
		for d in self.items:
			key = (d.item_code, d.ownership, d.cross_hire_order or "")
			balance[key] = balance.get(key, 0) - flt(d.qty)
			if balance[key] < -1e-6:
				frappe.throw(_("Cannot cancel: {0} from this delivery has already been off-hired.").format(frappe.bold(d.item_code)))
		last_billed = frappe.db.get_value("Rental Contract", self.rental_contract, "last_billed_upto")
		if last_billed and getdate(self.posting_date) <= getdate(last_billed):
			frappe.throw(_("Cannot cancel: this delivery has been billed. Cancel the billing schedules after {0} first.").format(self.posting_date))
		stock.cancel_stock_entries(self)
		ledger.delete_entries(self.doctype, self.name)
		self.take_from_contract()
		self.update_related()

	def update_related(self):
		from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
			sync_reservations,
		)

		ledger.update_contract_progress(self.rental_contract)
		sync_reservations(self.rental_contract)


def get_contract_job_types(rental_contract):
	"""The job types of a Job Type Contract (those of its Hire Order Contract); empty for any other contract."""
	src = frappe.db.get_value("Rental Contract", rental_contract, ["contract_type", "hire_order_contract"], as_dict=True)
	if not src or src.contract_type != "Job Type Contract" or not src.hire_order_contract:
		return []
	return frappe.get_all("Hire Order Contract Material", filters={"parent": src.hire_order_contract, "parenttype": "Hire Order Contract"},
		pluck="job_type", distinct=True, order_by="job_type")


@frappe.whitelist()
def get_contract_info(rental_contract: str):
	"""For the delivery form: the items on the contract and, for a job type contract, its job types."""
	contract = frappe.get_doc("Rental Contract", rental_contract)
	contract.check_permission("read")
	return {"items": [d.item_code for d in contract.items], "job_types": get_contract_job_types(rental_contract)}


@frappe.whitelist()
def get_dispatch_items(rental_contract: str, reservation: str | None = None):
	"""Suggest dispatch lines: own yard stock first, then received cross-hire material for this contract.
	The contract items are always physical stock items; for a job type contract they are the
	materials exploded from the Hire Order Contract. With a reservation, own stock is limited to its balance."""
	from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import (
		get_reservation_balance,
		get_reserved_stock,
	)

	contract = frappe.get_doc("Rental Contract", rental_contract)
	contract.check_permission("read")
	source = get_contract_source(rental_contract)
	reserved = get_reservation_balance(reservation) if reservation else {}
	reserved_stock = [(i, w, q) for (i, w), q in reserved.items()] if reservation else get_reserved_stock(rental_contract)
	own_warehouses = rw.own_warehouses()
	chos = frappe.get_all(
		"Cross Hire Order",
		filters={"docstatus": 1, "rental_contract": rental_contract, "status": ["!=", "Completed"]},
		fields=["name", "supplier", "receipt_warehouse"],
		order_by="creation asc",
	)
	out = []
	for d in contract.items:
		pending = flt(d.qty) - flt(d.dispatched_qty)
		if pending <= 0:
			continue
		base = {
			"item_code": d.item_code,
			"item_name": d.item_name,
			"uom": d.uom,
			"contract_qty": d.qty,
			"previously_delivered": d.dispatched_qty,
			"balance_to_deliver": pending,
		}
		taken = {}

		def take_own(warehouse, cap, balance=None):
			nonlocal pending
			if not warehouse or pending <= 0:
				return
			free = max(get_available_qty(d.item_code, warehouse, contract.name, source), 0) - taken.get(warehouse, 0)
			qty = min(pending, free, cap)
			if qty > 0:
				taken[warehouse] = taken.get(warehouse, 0) + qty
				pending -= qty
				row = dict(base, qty=qty, ownership="Own", source_warehouse=warehouse, location=rw.location_of(warehouse))
				if balance is not None:
					row["reservation_balance"] = balance
				out.append(row)

		# reserved stock first, warehouse by warehouse (only the named reservation's, when one is given)
		for item_code, warehouse, balance in reserved_stock:
			if item_code == d.item_code:
				take_own(warehouse, max(balance, 0), balance if reservation else None)
		if not reservation:
			# then free stock: the default own warehouse, then the other own warehouses
			for warehouse in own_warehouses:
				take_own(warehouse, pending)
		for cho in chos:
			if pending <= 0:
				break
			free = min(pending, max(ledger.get_cross_hire_undelivered(cho.name, d.item_code), 0))
			if free > 0:
				out.append(
					dict(base, qty=free, ownership="Cross Hire", cross_hire_order=cho.name, supplier=cho.supplier,
						source_warehouse=cho.receipt_warehouse, location=rw.location_of(cho.receipt_warehouse))
				)
				pending -= free
	return out


@frappe.whitelist()
def get_delivery_for_source(source_type: str, source_document: str):
	"""Selecting a Hire Order or Hire Order Contract on a delivery: find its Rental Contract and the lines to dispatch."""
	contract = get_contract_for_source(source_type, source_document)
	if not contract:
		frappe.throw(_("{0} {1} has no submitted Rental Contract yet. Create the Rental Contract first.").format(source_type, source_document))
	return {"rental_contract": contract, "items": get_dispatch_items(contract)}
