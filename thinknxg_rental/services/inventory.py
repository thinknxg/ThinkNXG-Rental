"""Rental inventory by warehouse and location.

One row per item, warehouse, ownership (and supplier / Cross Hire Order for supplier material) and
stock status. It answers, per warehouse:

* Available       own stock in an own rental warehouse not held by a reservation
* Reserved        own stock held by open reservations in that warehouse
* At Site         material at customer sites, counted against the warehouse it was delivered from
* In Custody      supplier (cross hire) material in a cross hire warehouse, not at a site
* Under Inspection / In Repair / Scrap   own stock in those warehouses

Figures come from ERPNext Bins (stock in a warehouse) and the Rental Ownership Ledger (what is at
site, whose it is). Nothing is stored here.
"""
import frappe
from frappe.utils import flt

from thinknxg_rental.services import ledger
from thinknxg_rental.services import warehouses as rw

STATUSES = ("Available", "Reserved", "At Site", "In Custody", "Under Inspection", "In Repair", "Scrap")


def rental_items(item_code=None, category=None):
	filters = {"disabled": 0}
	if item_code:
		filters["item"] = item_code
	if category:
		filters["category"] = category
	return {p.item: p for p in frappe.get_all("Rental Item Profile", filters=filters, fields=["item", "item_name", "category", "stock_uom"])}


def bins(items, warehouses):
	if not (items and warehouses):
		return {}
	rows = frappe.get_all("Bin", filters={"item_code": ["in", list(items)], "warehouse": ["in", list(warehouses)]},
		fields=["item_code", "warehouse", "actual_qty"])
	return {(r.item_code, r.warehouse): flt(r.actual_qty) for r in rows}


def reserved(items, warehouses):
	"""{(item, warehouse): open own-stock reservation balance}."""
	if not (items and warehouses):
		return {}
	rows = frappe.db.sql(
		"""
		select ri.item_code, ifnull(nullif(ri.source_warehouse, ''), r.source_warehouse) as warehouse,
			sum(ri.reserved_qty - ri.dispatched_qty - ri.released_qty) as qty
		from `tabRental Material Reservation Item` ri
		inner join `tabRental Material Reservation` r on r.name = ri.parent
		where r.docstatus = 1 and r.status not in ('Released', 'Dispatched') and ifnull(ri.ownership, 'Own') != 'Cross Hire'
			and ri.item_code in %(items)s
		group by ri.item_code, ifnull(nullif(ri.source_warehouse, ''), r.source_warehouse)
		""",
		{"items": tuple(items)},
		as_dict=True,
	)
	return {(r.item_code, r.warehouse): max(flt(r.qty), 0) for r in rows if r.warehouse in warehouses}


def at_site_by_origin(items):
	"""{(item, ownership, cross_hire_order, delivered_from): qty} at all customer sites. Cross hire
	movements recorded before warehouses were traced count against the order's receipt warehouse;
	own ones against the default own rental warehouse (single-yard history)."""
	if not items:
		return {}
	rows = frappe.db.sql(
		"""
		select l.item_code, l.ownership, ifnull(l.cross_hire_order, '') as cho,
			ifnull(nullif(l.origin_warehouse, ''), case when l.ownership = 'Cross Hire' then o.receipt_warehouse else '' end) as origin,
			sum(l.qty) as qty
		from `tabRental Ownership Ledger` l
		left join `tabCross Hire Order` o on o.name = l.cross_hire_order
		where l.position_type = %(pt)s and l.item_code in %(items)s
		group by l.item_code, l.ownership, ifnull(l.cross_hire_order, ''), origin
		""",
		{"pt": ledger.AT_SITE, "items": tuple(items)},
		as_dict=True,
	)
	default = rw.default_own_warehouse() or ""
	out = {}
	for r in rows:
		origin = r.origin or (default if r.ownership == "Own" else "")
		key = (r.item_code, r.ownership, r.cho, origin)
		out[key] = out.get(key, 0) + flt(r.qty)
	return {k: v for k, v in out.items() if abs(v) > 1e-9}


def custody_by_warehouse(items=None, cross_hire_order=None):
	"""{(cross_hire_order, item, warehouse): supplier material in our custody there} - received into
	(or moved into) the warehouse, less returned / lost / moved out. Losses recorded before warehouses
	were traced count against the order's receipt warehouse."""
	conditions, values = ["l.position_type = %(pt)s"], {"pt": ledger.CUSTODY}
	if items:
		conditions.append("l.item_code in %(items)s")
		values["items"] = tuple(items)
	if cross_hire_order:
		conditions.append("l.cross_hire_order = %(cho)s")
		values["cho"] = cross_hire_order
	rows = frappe.db.sql(
		f"""
		select l.cross_hire_order as cho, l.item_code,
			case when l.movement_type = 'Loss' and ifnull(l.origin_warehouse, '') = '' then o.receipt_warehouse
				when l.movement_type = 'Loss' then l.origin_warehouse else l.warehouse end as warehouse,
			sum(l.qty) as qty
		from `tabRental Ownership Ledger` l
		left join `tabCross Hire Order` o on o.name = l.cross_hire_order
		where {" and ".join(conditions)}
		group by l.cross_hire_order, l.item_code, warehouse
		""",
		values,
		as_dict=True,
	)
	out = {}
	for r in rows:
		key = (r.cho, r.item_code, r.warehouse)
		out[key] = out.get(key, 0) + flt(r.qty)
	return out


def in_custody_not_at_site(items=None, cross_hire_order=None):
	"""{(cross_hire_order, item, warehouse): supplier material in the warehouse and not at a site}."""
	custody = custody_by_warehouse(items, cross_hire_order)
	at_site = at_site_by_origin(items or list({k[1] for k in custody}))
	out = dict(custody)
	for (item, ownership, cho, origin), qty in at_site.items():
		if ownership != "Cross Hire" or (cross_hire_order and cho != cross_hire_order):
			continue
		key = (cho, item, origin)
		out[key] = out.get(key, 0) - qty
	return {k: v for k, v in out.items() if abs(v) > 1e-9}


def get_inventory(filters=None):
	"""Inventory rows: item, warehouse, location, ownership, supplier, cross hire order, status, qty."""
	f = frappe._dict(filters or {})
	profiles = rental_items(f.get("item_code"), f.get("category"))
	if not profiles:
		return []
	items = list(profiles)
	s = rw.settings()
	own = rw.own_warehouses(active_only=False)
	special = {s.inspection_warehouse: "Under Inspection", s.repair_warehouse: "In Repair", s.scrap_warehouse: "Scrap"}
	special = {w: st for w, st in special.items() if w}
	stock = bins(items, own + list(special))
	held = reserved(items, set(own))
	rows = []

	def add(item, warehouse, ownership, status, qty, supplier=None, cho=None):
		if abs(flt(qty)) <= 1e-9:
			return
		p = profiles[item]
		rows.append(frappe._dict(item_code=item, item_name=p.item_name, category=p.category, uom=p.stock_uom,
			warehouse=warehouse or None, location=rw.location_of(warehouse) if warehouse else None, ownership=ownership,
			supplier=supplier, cross_hire_order=cho, stock_status=status, qty=flt(qty),
			warehouse_active=int(rw.is_active(warehouse)) if warehouse in own else None))

	for item in items:
		for w in own:
			actual, res = stock.get((item, w), 0), held.get((item, w), 0)
			add(item, w, "Own", "Reserved", min(res, max(actual, 0)))
			add(item, w, "Own", "Available", actual - min(res, max(actual, 0)))
		for w, status in special.items():
			add(item, w, "Own", status, stock.get((item, w), 0))
	suppliers = {}

	def supplier_of(cho):
		if cho and cho not in suppliers:
			suppliers[cho] = frappe.db.get_value("Cross Hire Order", cho, "supplier")
		return suppliers.get(cho)

	for (item, ownership, cho, origin), qty in at_site_by_origin(items).items():
		add(item, origin, ownership, "At Site", qty, supplier_of(cho) if cho else None, cho or None)
	for (cho, item, warehouse), qty in in_custody_not_at_site(items).items():
		if item in profiles:
			add(item, warehouse, "Cross Hire", "In Custody", qty, supplier_of(cho), cho)

	def keep(r):
		if f.get("warehouse") and r.warehouse != f.warehouse:
			return False
		if f.get("location") and (r.location or "") != f.location:
			return False
		if f.get("ownership") and r.ownership != f.ownership:
			return False
		if f.get("supplier") and r.supplier != f.supplier:
			return False
		if f.get("stock_status") and r.stock_status != f.stock_status:
			return False
		return True

	rows = [r for r in rows if keep(r)]
	order = {st: i for i, st in enumerate(STATUSES)}
	rows.sort(key=lambda r: (r.location or "~", r.warehouse or "~", r.item_code, order.get(r.stock_status, 99), r.cross_hire_order or ""))
	return rows


def get_locations():
	return sorted({loc for loc in rw.locations().values() if loc})
