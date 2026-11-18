import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from thinknxg_rental.services import warehouses as rw
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
		for d in self.items:
			if not frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
				frappe.throw(
					_("Row #{0}: {1} is not a stock item. Reserve the physical rental items, never the job type.").format(
						d.idx, frappe.bold(d.item_code)
					)
				)
			if flt(d.required_qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
		if self.source_warehouse and self.docstatus == 0:
			rw.validate_own(self.source_warehouse, _("Default Source Warehouse: "), company=self.company)
		self.place_rows()
		# one row per item and warehouse: the same item can be reserved in several warehouses
		check_duplicate_items(self, ("item_code", "source_warehouse"))
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

	def place_rows(self):
		"""Every row has its own warehouse. Rows the system places (needs_plan) are split over the own
		rental warehouses that have the item free - the default first, then the most free - and what no
		own warehouse can cover stays as shortfall on the last own row; with no own stock free anywhere
		the row is to cross hire, in the warehouse cross-hired units arrive in."""
		if self.docstatus != 0:
			return
		contract = self.get_contract() if (self.rental_contract or self.source_document) else None
		cross_hire_warehouses = get_cross_hire_warehouses()
		taken = {}  # (item, warehouse) -> qty this document already holds there
		fixed, placed = [], []
		for d in self.items:
			(placed if self.needs_plan(d, cross_hire_warehouses) else fixed).append(d)
		for d in fixed:
			d.ownership = "Cross Hire" if d.source_warehouse in cross_hire_warehouses else "Own"
			if d.ownership == "Own":
				key = (d.item_code, d.source_warehouse)
				taken[key] = taken.get(key, 0) + min(flt(d.required_qty), max(free_qty(d.item_code, d.source_warehouse, self.name), 0))
		if not placed:
			return
		by_key = {(d.item_code, d.source_warehouse): d for d in fixed}
		order = []
		for d in self.items:
			if d not in placed:
				order.append(d)
				continue
			parts = plan_rows(d.item_code, flt(d.required_qty), self.source_warehouse, self.name, contract, taken)
			for i, (warehouse, ownership, qty) in enumerate(parts):
				existing = by_key.get((d.item_code, warehouse))
				if existing is not None:
					existing.required_qty = flt(existing.required_qty) + qty
					continue
				if i == 0:
					row = d
				else:
					row = self.append("items", {"item_code": d.item_code, "item_name": d.item_name, "uom": d.uom})
					self.items.remove(row)
				row.source_warehouse, row.ownership, row.required_qty = warehouse, ownership, qty
				by_key[(d.item_code, warehouse)] = row
				order.append(row)
		self.items = order
		for i, d in enumerate(self.items, 1):
			d.idx = i

	def set_availability(self, lock=False):
		totals = frappe._dict(required=0, reserved=0, shortfall=0)
		cross_hire_warehouses = get_cross_hire_warehouses()
		if lock:
			# two reservations submitted at the same time queue on the stock rows they draw from
			rw.lock_bins((d.item_code, d.source_warehouse) for d in self.items if d.ownership != "Cross Hire")
		for d in self.items:
			if not d.source_warehouse:
				frappe.throw(_("Row #{0}: set a Source Warehouse for {1}").format(d.idx, frappe.bold(d.item_code)))
			d.ownership = "Cross Hire" if d.source_warehouse in cross_hire_warehouses else "Own"
			wh = frappe.get_cached_value("Warehouse", d.source_warehouse, ["is_group", "company"], as_dict=True)
			if wh.is_group:
				frappe.throw(_("Row #{0}: {1} is a group warehouse. Pick the warehouse that holds the stock.").format(d.idx, d.source_warehouse))
			if wh.company != self.company:
				frappe.throw(_("Row #{0}: warehouse {1} belongs to company {2}").format(d.idx, d.source_warehouse, wh.company))
			if d.ownership == "Own":
				rw.validate_own(d.source_warehouse, _("Row #{0}: ").format(d.idx), company=self.company)
			d.location = rw.location_of(d.source_warehouse)
			d.actual_qty = get_bin_qty(d.item_code, d.source_warehouse, for_update=lock)
			if d.ownership == "Cross Hire":
				# cross-hired stock belongs to its Cross Hire Order, never to an own-stock reservation:
				# the whole row is shortfall, to be covered by the Cross Hire Order
				d.other_reserved_qty = 0
				d.available_qty = 0
			else:
				d.other_reserved_qty = get_reserved_for_others(d.item_code, d.source_warehouse, reservation=self.name, for_update=lock)
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

	def needs_plan(self, d, cross_hire_warehouses):
		"""Rows the system places: no warehouse yet; a cross hire row (own stock may have come free since);
		or a row left on the header default where that warehouse has no free stock of the item (it would
		reserve nothing there). A warehouse picked by hand that holds stock is kept."""
		if self.docstatus != 0:
			return False
		if not d.source_warehouse or d.source_warehouse in cross_hire_warehouses:
			return True
		return d.source_warehouse == self.source_warehouse and free_qty(d.item_code, d.source_warehouse, self.name) <= 0

	def _submit(self):
		# Lock the stock rows first, before Frappe locks this document: every reservation and delivery
		# of the same item and warehouse then queues at the same place and none waits on another's
		# document (no deadlock), and the figures read on submit are the latest committed ones.
		rw.lock_bins((d.item_code, d.source_warehouse) for d in self.items if d.ownership != "Cross Hire")
		return super()._submit()

	def before_submit(self):
		# availability may have moved since the draft was saved; the warehouses stay as saved
		self.set_availability(lock=True)
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


def get_rentable_warehouses(company=None):
	"""Own rental warehouses own stock can be reserved in: the active rows of Own Rental Warehouses
	(the default first), of the company."""
	out = rw.own_warehouses()
	if company:
		out = [w for w in out if frappe.get_cached_value("Warehouse", w, "company") == company]
	return out


def free_qty(item_code, warehouse, reservation=None):
	"""Own stock in a warehouse not held by other reservations."""
	return get_bin_qty(item_code, warehouse) - get_reserved_for_others(item_code, warehouse, reservation=reservation)


def get_cross_hire_warehouses():
	"""Warehouses that hold cross-hired (supplier) stock: the Cross Hire Warehouses of Rental Settings
	(inactive ones too: material already in them is still supplier-owned) and each site's cross hire
	warehouse (where Direct to Site cross hire is received)."""
	out = set(rw.cross_hire_warehouses(active_only=False))
	out.update(frappe.get_all("Rental Site", filters={"cross_hire_site_warehouse": ["is", "set"]}, pluck="cross_hire_site_warehouse"))
	return {w for w in out if w}


def cross_hire_warehouse(item_code, rental_contract=None, reservation=None):
	"""Where cross-hired units of this item arrive: the receipt warehouse of an open Cross Hire Order for
	this contract or reservation that has the item, else the default Cross Hire Warehouse."""
	or_filters = []
	if rental_contract:
		or_filters.append(["rental_contract", "=", rental_contract])
	if reservation:
		or_filters.append(["material_reservation", "=", reservation])
	if or_filters:
		chos = frappe.get_all("Cross Hire Order", filters={"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]},
			or_filters=or_filters, fields=["name", "receipt_warehouse"], order_by="creation asc")
		for cho in chos:
			if cho.receipt_warehouse and frappe.db.exists("Cross Hire Order Item", {"parent": cho.name, "item_code": item_code}):
				return cho.receipt_warehouse
	return rw.default_cross_hire_warehouse()


def plan_rows(item_code, required_qty, default=None, reservation=None, rental_contract=None, taken=None):
	"""[(warehouse, supply, qty)] covering required_qty: own stock split over the own rental warehouses
	with the item free - the default first when it has any, then the most free - with what none can cover
	left as shortfall on the last own row; with no own stock free anywhere, one cross hire row.

	taken: {(item, warehouse): qty} already held by other rows of the same document; updated."""
	taken = {} if taken is None else taken
	default = default or rw.default_own_warehouse()

	def free(w):
		return free_qty(item_code, w, reservation) - taken.get((item_code, w), 0)

	candidates = [(free(w), w) for w in get_rentable_warehouses()]
	candidates = [(q, w) for q, w in candidates if q > 1e-9]
	if default and free(default) >= required_qty:
		candidates = [(free(default), default)]
	else:
		candidates.sort(key=lambda c: (c[1] != default, -c[0]))
	parts, remaining = [], flt(required_qty)
	for q, w in candidates:
		if remaining <= 1e-9:
			break
		take = min(q, remaining)
		parts.append([w, "Own", take])
		taken[(item_code, w)] = taken.get((item_code, w), 0) + take
		remaining -= take
	if remaining > 1e-9:
		if parts:
			parts[-1][2] += remaining  # shortfall on the last own row: the reservation still asks for it
		else:
			cross = cross_hire_warehouse(item_code, rental_contract, reservation)
			parts.append([cross, "Cross Hire", remaining] if cross else [default, "Own", remaining])
	return [tuple(p) for p in parts]


def plan_row(item_code, company=None, default=None, required_qty=0, reservation=None, rental_contract=None):
	"""(source warehouse, supply) of the first part of plan_rows (the live figures of one form row)."""
	warehouse, ownership, _qty = plan_rows(item_code, flt(required_qty) or 1, default, reservation, rental_contract)[0]
	return warehouse, ownership


def suggest_source_warehouse(item_code, company=None, default=None, required_qty=0, reservation=None):
	"""The default warehouse when it can cover the row; otherwise the own rental warehouse with the
	most free stock of this item; the default again when nothing has any."""
	def free(warehouse):
		return free_qty(item_code, warehouse, reservation)

	default = default or rw.default_own_warehouse()
	if default and free(default) >= max(flt(required_qty), 1e-6):
		return default
	best = max(((free(w), w) for w in get_rentable_warehouses(company)), default=(0, None))
	if not default:
		return best[1]
	return best[1] if best[1] and best[0] > max(free(default), 0) else default


@frappe.whitelist()
def get_row_availability(item_code: str, company: str, warehouse: str | None = None, default_warehouse: str | None = None,
		required_qty: float = 0, reservation: str | None = None, rental_contract: str | None = None):
	"""Live figures for one reservation row, and its warehouse and supply (Own / Cross Hire) when none
	is chosen yet. The same placement as on save (plan_rows); `plan` shows how saving will split it."""
	frappe.has_permission("Rental Material Reservation", "read", throw=True)
	cross_hire_warehouses = get_cross_hire_warehouses()
	plan = []
	if warehouse:
		ownership = "Cross Hire" if warehouse in cross_hire_warehouses else "Own"
	else:
		plan = plan_rows(item_code, flt(required_qty) or 1, default_warehouse, reservation, rental_contract)
		warehouse, ownership, _qty = plan[0]
	actual = get_bin_qty(item_code, warehouse)
	others = 0 if ownership == "Cross Hire" else get_reserved_for_others(item_code, warehouse, reservation=reservation)
	elsewhere = []
	for w in get_rentable_warehouses(company):
		if w != warehouse:
			qty = get_bin_qty(item_code, w) - get_reserved_for_others(item_code, w, reservation=reservation)
			if qty > 0:
				elsewhere.append({"warehouse": w, "location": rw.location_of(w), "available_qty": qty})
	return {
		"source_warehouse": warehouse,
		"location": rw.location_of(warehouse),
		"ownership": ownership,
		"actual_qty": actual,
		"other_reserved_qty": others,
		"available_qty": 0 if ownership == "Cross Hire" else max(actual - others, 0),
		"elsewhere": sorted(elsewhere, key=lambda r: -r["available_qty"]),
		"plan": [{"source_warehouse": w, "ownership": o, "required_qty": q, "location": rw.location_of(w)} for w, o, q in plan],
	}


def get_reservation_warehouses(reservation):
	"""{item_code: source warehouse} of the own-stock rows of one reservation (an item reserved in several
	warehouses: the one holding most). Cross hire rows are left out: their material leaves from its Cross
	Hire Order's warehouse, not as reserved own stock. See get_reservation_allocations for every warehouse."""
	out = {}
	for (item_code, warehouse), qty in sorted(get_reservation_allocations(reservation, balance=False).items(), key=lambda kv: kv[1]):
		out[item_code] = warehouse
	return out


def get_reservation_allocations(reservation, balance=True):
	"""{(item_code, warehouse): qty} of the own-stock rows of one reservation: the open balance
	(reserved - dispatched - released), or with balance=False the reserved qty."""
	default = frappe.db.get_value("Rental Material Reservation", reservation, "source_warehouse")
	rows = frappe.get_all(
		"Rental Material Reservation Item",
		filters={"parent": reservation, "parenttype": "Rental Material Reservation", "ownership": ["!=", "Cross Hire"]},
		fields=["item_code", "source_warehouse", "reserved_qty", "dispatched_qty", "released_qty"],
		order_by="idx asc",
	)
	out = {}
	for r in rows:
		key = (r.item_code, r.source_warehouse or default)
		qty = flt(r.reserved_qty) - ((flt(r.dispatched_qty) + flt(r.released_qty)) if balance else 0)
		out[key] = out.get(key, 0) + qty
	return out


def get_reserved_stock(rental_contract):
	"""[(item_code, warehouse, open balance)] across the contract's live reservations, oldest first."""
	out = []
	for name in get_contract_reservations(rental_contract):
		doc = frappe.get_doc("Rental Material Reservation", name)
		if doc.status == "Released":
			continue
		for d in doc.items:
			if d.ownership == "Cross Hire":
				continue
			balance = flt(d.reserved_qty) - flt(d.dispatched_qty) - flt(d.released_qty)
			if balance > 0:
				out.append((d.item_code, d.source_warehouse or doc.source_warehouse, balance))
	return out


def get_reservation_balance(reservation):
	"""{(item_code, warehouse): reserved - dispatched - released} of the own-stock rows of one reservation."""
	return get_reservation_allocations(reservation, balance=True)


def sync_reservations(rental_contract):
	"""Allocate the contract's own-stock dispatches against its reservations (idempotent).

	Each reservation row is an allocation of one item in one warehouse. A delivery that names a
	reservation fills that reservation's rows of the same item and warehouse first; everything else, and
	any overflow, is spread over the contract's rows of the same item and warehouse, oldest first; what
	is still left (deliveries made before warehouses were tracked per row) over the item's other rows."""
	rows = frappe.db.sql(
		"""
		select ifnull(p.rental_material_reservation, '') as reservation, i.item_code,
			ifnull(i.source_warehouse, '') as warehouse, sum(i.qty) as qty
		from `tabHire Delivery Item` i
		inner join `tabHire Delivery Order` p on p.name = i.parent
		where p.docstatus = 1 and p.rental_contract = %s and i.ownership = 'Own'
		group by ifnull(p.rental_material_reservation, ''), i.item_code, ifnull(i.source_warehouse, '')
		""",
		rental_contract,
		as_dict=True,
	)
	docs = [frappe.get_doc("Rental Material Reservation", n) for n in get_contract_reservations(rental_contract)]
	known = {d.name for d in docs}
	named, loose = {}, {}
	for r in rows:
		if r.reservation and r.reservation in known:
			key = (r.reservation, r.item_code, r.warehouse)
			named[key] = named.get(key, 0) + flt(r.qty)
		else:
			key = (r.item_code, r.warehouse)
			loose[key] = loose.get(key, 0) + flt(r.qty)

	def cap(doc, d):
		# released rows keep only what was dispatched before the release
		return flt(d.reserved_qty) - (flt(d.released_qty) if doc.status == "Released" else 0)

	def wh(doc, d):
		return d.source_warehouse or doc.source_warehouse or ""

	own_rows = [(doc, d) for doc in docs for d in doc.items if d.ownership != "Cross Hire"]
	allocated = {d.name: 0 for doc in docs for d in doc.items}
	# 1. the named reservation, same item and warehouse
	for doc, d in own_rows:
		key = (doc.name, d.item_code, wh(doc, d))
		take = min(cap(doc, d) - allocated[d.name], named.get(key, 0))
		if take > 0:
			allocated[d.name] += take
			named[key] -= take
	for (reservation, item_code, warehouse), qty in named.items():
		if qty > 1e-9:
			loose[(item_code, warehouse)] = loose.get((item_code, warehouse), 0) + qty
	# 2. any reservation of the contract, same item and warehouse
	for doc, d in own_rows:
		key = (d.item_code, wh(doc, d))
		take = min(cap(doc, d) - allocated[d.name], max(loose.get(key, 0), 0))
		if take > 0:
			allocated[d.name] += take
			loose[key] -= take
	# 3. what is left, by item (history from before per-warehouse allocations)
	left = {}
	for (item_code, _w), qty in loose.items():
		left[item_code] = left.get(item_code, 0) + max(qty, 0)
	for doc, d in own_rows:
		take = min(cap(doc, d) - allocated[d.name], left.get(d.item_code, 0))
		if take > 0:
			allocated[d.name] += take
			left[d.item_code] -= take
	for doc in docs:
		open_balance = 0
		for d in doc.items:
			if flt(d.dispatched_qty) != allocated[d.name]:
				d.db_set("dispatched_qty", allocated[d.name], update_modified=False)
			if d.ownership != "Cross Hire":
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
