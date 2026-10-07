import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from thinknxg_rental.services import ledger
from thinknxg_rental.services.utils import (
	check_duplicate_items,
	get_bin_qty,
	get_contract_for_source,
	get_contract_source,
	get_reserved_for_others,
)

SOURCE_TYPES = ("Hire Order", "Hire Order Contract")


class RentalMaterialReservation(Document):
	"""A soft reservation: it never posts to the stock ledger, it only reduces the quantity
	that other contracts are allowed to reserve or dispatch from the yard.

	It can originate from a Hire Order (its stock items), a Hire Order Contract (its job types
	exploded into physical rental items) or a Rental Contract. Lines are always stock items."""

	def validate(self):
		self.set_source()
		check_duplicate_items(self)
		for d in self.items:
			if not frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
				frappe.throw(
					_("Row #{0}: {1} is not a stock item. Reserve the physical rental items, never the job type.").format(
						d.idx, frappe.bold(d.item_code)
					)
				)
		self.set_availability()

	def set_source(self):
		if self.rental_contract:
			src = get_contract_source(self.rental_contract)
			if src:
				self.source_type, self.source_document = src
		if not (self.rental_contract or (self.source_type and self.source_document)):
			frappe.throw(_("Select a Rental Contract, or a Hire Order / Hire Order Contract as the rental source"))
		if self.source_type and self.source_type not in SOURCE_TYPES:
			frappe.throw(_("Rental Source Type must be Hire Order or Hire Order Contract"))
		if self.source_type and self.source_document:
			if frappe.db.get_value(self.source_type, self.source_document, "docstatus") != 1:
				frappe.throw(_("{0} {1} is not submitted").format(self.source_type, self.source_document))
			if not self.rental_contract:
				self.rental_contract = get_contract_for_source(self.source_type, self.source_document)
		else:
			self.source_type = self.source_document = None
		self.hire_order = self.source_document if self.source_type == "Hire Order" else None
		self.hire_order_contract = self.source_document if self.source_type == "Hire Order Contract" else None

	def set_availability(self):
		totals = frappe._dict(required=0, reserved=0, shortfall=0)
		for d in self.items:
			if flt(d.required_qty) <= 0:
				frappe.throw(_("Row #{0}: Required Qty must be greater than zero").format(d.idx))
			# every row is reserved in its own warehouse; the header only supplies the default
			d.source_warehouse = d.source_warehouse or suggest_source_warehouse(
				d.item_code, self.company, self.source_warehouse, flt(d.required_qty)
			)
			wh = frappe.get_cached_value("Warehouse", d.source_warehouse, ["is_group", "company"], as_dict=True)
			if wh.is_group:
				frappe.throw(_("Row #{0}: {1} is a group warehouse. Pick the warehouse that holds the stock.").format(d.idx, d.source_warehouse))
			if wh.company != self.company:
				frappe.throw(_("Row #{0}: warehouse {1} belongs to company {2}").format(d.idx, d.source_warehouse, wh.company))
			d.actual_qty = get_bin_qty(d.item_code, d.source_warehouse)
			d.other_reserved_qty = get_reserved_for_others(d.item_code, d.source_warehouse, reservation=self.name)
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
		return self.rental_contract or get_contract_for_source(self.source_type, self.source_document)

	@frappe.whitelist()
	def release(self):
		"""Hand the undispatched balance back to the available pool."""
		self.check_permission("write")
		if self.docstatus != 1 or self.status in ("Released", "Dispatched"):
			frappe.throw(_("Nothing to release"))
		for d in self.items:
			d.db_set("released_qty", max(flt(d.reserved_qty) - flt(d.dispatched_qty), 0), update_modified=False)
		self.db_set("status", "Released")


def get_contract_reservations(rental_contract):
	"""Submitted reservations of a contract, including ones raised from its source before it existed."""
	names = set(frappe.get_all("Rental Material Reservation", filters={"rental_contract": rental_contract, "docstatus": 1}, pluck="name"))
	src = get_contract_source(rental_contract)
	if src:
		names.update(
			frappe.get_all(
				"Rental Material Reservation",
				filters={"source_type": src[0], "source_document": src[1], "docstatus": 1},
				pluck="name",
			)
		)
	if not names:
		return []
	return frappe.get_all(
		"Rental Material Reservation", filters={"name": ["in", list(names)]}, pluck="name", order_by="creation asc"
	)


def get_rentable_warehouses(company):
	"""Leaf warehouses own rental stock can be reserved in: not customer sites, cross hire,
	inspection, repair or scrap."""
	from thinknxg_rental.services.utils import get_settings

	settings = get_settings()
	excluded = {
		settings.cross_hire_yard_warehouse, settings.inspection_warehouse, settings.repair_warehouse, settings.scrap_warehouse,
	}
	for site in frappe.get_all("Rental Site", fields=["site_warehouse", "cross_hire_site_warehouse"]):
		excluded.update((site.site_warehouse, site.cross_hire_site_warehouse))
	names = frappe.get_all("Warehouse", filters={"company": company, "is_group": 0, "disabled": 0}, pluck="name")
	return [n for n in names if n not in excluded]


def suggest_source_warehouse(item_code, company, default=None, required_qty=0):
	"""The default warehouse when it can cover the row; otherwise the rentable warehouse with the
	most free stock of this item; the default again when nothing has any."""
	def free(warehouse):
		return get_bin_qty(item_code, warehouse) - get_reserved_for_others(item_code, warehouse)

	if default and free(default) >= max(flt(required_qty), 1e-6):
		return default
	allowed = set(get_rentable_warehouses(company))
	stocked = frappe.get_all(
		"Bin", filters={"item_code": item_code, "actual_qty": [">", 0]}, pluck="warehouse"
	)
	best = max(((free(w), w) for w in stocked if w in allowed), default=(0, None))
	if not default:
		return best[1]
	return best[1] if best[1] and best[0] > max(free(default), 0) else default


@frappe.whitelist()
def get_row_availability(item_code: str, company: str, warehouse: str | None = None, default_warehouse: str | None = None,
		required_qty: float = 0, reservation: str | None = None):
	"""Live figures for one reservation row, and the warehouse to use when none is chosen yet."""
	frappe.has_permission("Rental Material Reservation", "read", throw=True)
	warehouse = warehouse or suggest_source_warehouse(item_code, company, default_warehouse, flt(required_qty))
	actual = get_bin_qty(item_code, warehouse)
	others = get_reserved_for_others(item_code, warehouse, reservation=reservation)
	elsewhere = []
	for w in get_rentable_warehouses(company):
		if w != warehouse:
			qty = get_bin_qty(item_code, w) - get_reserved_for_others(item_code, w, reservation=reservation)
			if qty > 0:
				elsewhere.append({"warehouse": w, "available_qty": qty})
	return {
		"source_warehouse": warehouse,
		"actual_qty": actual,
		"other_reserved_qty": others,
		"available_qty": max(actual - others, 0),
		"elsewhere": sorted(elsewhere, key=lambda r: -r["available_qty"]),
	}


def get_reservation_warehouses(reservation):
	"""{item_code: source warehouse} for one reservation."""
	default = frappe.db.get_value("Rental Material Reservation", reservation, "source_warehouse")
	rows = frappe.get_all(
		"Rental Material Reservation Item",
		filters={"parent": reservation, "parenttype": "Rental Material Reservation"},
		fields=["item_code", "source_warehouse"],
	)
	return {r.item_code: r.source_warehouse or default for r in rows}


def get_reserved_stock(rental_contract):
	"""[(item_code, warehouse, open balance)] across the contract's live reservations, oldest first."""
	out = []
	for name in get_contract_reservations(rental_contract):
		doc = frappe.get_doc("Rental Material Reservation", name)
		if doc.status == "Released":
			continue
		for d in doc.items:
			balance = flt(d.reserved_qty) - flt(d.dispatched_qty) - flt(d.released_qty)
			if balance > 0:
				out.append((d.item_code, d.source_warehouse or doc.source_warehouse, balance))
	return out


def get_reservation_balance(reservation):
	"""{item_code: reserved - dispatched - released} for one reservation."""
	rows = frappe.get_all(
		"Rental Material Reservation Item",
		filters={"parent": reservation, "parenttype": "Rental Material Reservation"},
		fields=["item_code", "reserved_qty", "dispatched_qty", "released_qty"],
	)
	return {r.item_code: flt(r.reserved_qty) - flt(r.dispatched_qty) - flt(r.released_qty) for r in rows}


def sync_reservations(rental_contract):
	"""Allocate the contract's own-stock dispatches against its reservations (idempotent).

	A delivery that names a reservation fills that reservation first; everything else, and any
	overflow, is spread over the contract's reservations oldest first."""
	rows = frappe.db.sql(
		"""
		select ifnull(p.rental_material_reservation, '') as reservation, i.item_code, sum(i.qty) as qty
		from `tabHire Delivery Item` i
		inner join `tabHire Delivery Order` p on p.name = i.parent
		where p.docstatus = 1 and p.rental_contract = %s and i.ownership = 'Own'
		group by ifnull(p.rental_material_reservation, ''), i.item_code
		""",
		rental_contract,
		as_dict=True,
	)
	named, loose = {}, {}
	for r in rows:
		if r.reservation:
			named[(r.reservation, r.item_code)] = flt(r.qty)
		else:
			loose[r.item_code] = loose.get(r.item_code, 0) + flt(r.qty)

	docs = [frappe.get_doc("Rental Material Reservation", n) for n in get_contract_reservations(rental_contract)]
	known = {d.name for d in docs}
	for (reservation, item_code), qty in named.items():
		if reservation not in known:
			loose[item_code] = loose.get(item_code, 0) + qty

	def cap(doc, d):
		# released rows keep only what was dispatched before the release
		return flt(d.reserved_qty) - (flt(d.released_qty) if doc.status == "Released" else 0)

	allocated = {}
	for doc in docs:
		for d in doc.items:
			take = min(cap(doc, d), named.get((doc.name, d.item_code), 0))
			allocated[d.name] = take
			loose[d.item_code] = loose.get(d.item_code, 0) + named.get((doc.name, d.item_code), 0) - take
	for doc in docs:
		for d in doc.items:
			take = min(cap(doc, d) - allocated[d.name], max(loose.get(d.item_code, 0), 0))
			if take > 0:
				allocated[d.name] += take
				loose[d.item_code] -= take
	for doc in docs:
		open_balance = 0
		for d in doc.items:
			d.db_set("dispatched_qty", allocated[d.name], update_modified=False)
			open_balance += flt(d.reserved_qty) - allocated[d.name] - flt(d.released_qty)
		if doc.status != "Released":
			if open_balance <= 1e-6 and flt(doc.total_reserved_qty) > 0:
				status = "Dispatched"
			else:
				status = "Partially Reserved" if flt(doc.total_shortfall_qty) > 0 else "Reserved"
			doc.db_set("status", status, update_modified=False)


@frappe.whitelist()
def get_source_items(source_type: str, source_document: str):
	"""Stock items to reserve for a rental source. A Hire Order Contract is exploded:
	job type -> its rental items -> physical stock items."""
	if source_type not in SOURCE_TYPES:
		frappe.throw(_("Rental Source Type must be Hire Order or Hire Order Contract"))
	doc = frappe.get_doc(source_type, source_document)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("{0} {1} is not submitted").format(source_type, source_document))
	totals = {}
	rows = doc.items if source_type == "Hire Order" else doc.materials
	for d in rows:
		totals[d.item_code] = totals.get(d.item_code, 0) + flt(d.qty)
	contract = get_contract_for_source(source_type, source_document)
	if contract:
		# only what is still to be dispatched
		pending = {d.item_code: flt(d.pending_qty) for d in frappe.get_doc("Rental Contract", contract).items}
		totals = {k: min(v, pending.get(k, v)) for k, v in totals.items()}
	out = []
	for item_code, qty in totals.items():
		if qty <= 0:
			continue
		item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
		out.append({"item_code": item_code, "item_name": item.item_name, "uom": item.stock_uom, "required_qty": qty})
	return {
		"items": out,
		"rental_contract": contract,
		"customer": doc.customer,
		"company": doc.company,
		"rental_site": doc.rental_site,
		"required_from": doc.required_from,
	}


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
			"rental_contract": source.get_contract(),
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
