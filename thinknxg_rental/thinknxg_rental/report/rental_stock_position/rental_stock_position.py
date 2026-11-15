import frappe
from frappe import _
from frappe.utils import cint, flt

from thinknxg_rental.services import inventory
from thinknxg_rental.services import warehouses as rw
from thinknxg_rental.services.utils import get_settings
from thinknxg_rental.thinknxg_rental.doctype.rental_material_reservation.rental_material_reservation import get_cross_hire_warehouses


def execute(filters=None):
	"""Per item, over the own rental warehouses (all of them, or the selected warehouse / location);
	with Group by Warehouse one row per item and warehouse, own and cross hire."""
	filters = frappe._dict(filters or {})
	if cint(filters.get("group_by_warehouse")):
		return execute_by_warehouse(filters)
	settings = get_settings()
	item_filters = {"disabled": 0}
	if filters.get("category"):
		item_filters["category"] = filters.category
	if filters.get("item_code"):
		item_filters["item"] = filters.item_code
	profiles = frappe.get_all(
		"Rental Item Profile", filters=item_filters, fields=["item", "item_name", "category", "stock_uom"], order_by="item"
	)
	if not profiles:
		return get_columns(), []
	items = [p.item for p in profiles]
	scoped = bool(filters.get("warehouse") or filters.get("location"))
	own = selected_warehouses(filters, rw.own_warehouses(active_only=False))

	def bins(warehouses):
		warehouses = [w for w in warehouses if w]
		if not warehouses:
			return {}
		out = {}
		for item_code, qty in frappe.get_all(
			"Bin", filters={"warehouse": ["in", warehouses], "item_code": ["in", items]}, fields=["item_code", "actual_qty"], as_list=True
		):
			out[item_code] = out.get(item_code, 0) + flt(qty)
		return out

	yard = bins(own)
	# inspection, repair and scrap belong to no location: shown when the whole company is shown
	inspection, repair, scrap = ({} if scoped else bins([settings.get(f)]) for f in ("inspection_warehouse", "repair_warehouse", "scrap_warehouse"))
	held = inventory.reserved(items, set(own))
	reserved = {}
	for (item_code, _w), qty in held.items():
		reserved[item_code] = reserved.get(item_code, 0) + qty
	at_site = inventory.at_site_by_origin(items)
	own_set, cross_scope = set(own), set(selected_warehouses(filters, list(get_cross_hire_warehouses())))
	ledger = {}
	for (item_code, ownership, _cho, origin), qty in at_site.items():
		if scoped and origin not in (own_set if ownership == "Own" else cross_scope):
			continue
		key = (item_code, "At Site", ownership)
		ledger[key] = ledger.get(key, 0) + qty
	for (_cho, item_code, warehouse), qty in inventory.in_custody_not_at_site(items).items():
		if scoped and warehouse not in cross_scope:
			continue
		key = (item_code, "Not at Site", "Cross Hire")
		ledger[key] = ledger.get(key, 0) + qty

	data = []
	for p in profiles:
		site_own = ledger.get((p.item, "At Site", "Own"), 0)
		site_cross = ledger.get((p.item, "At Site", "Cross Hire"), 0)
		cross_idle = ledger.get((p.item, "Not at Site", "Cross Hire"), 0)
		yard_qty = flt(yard.get(p.item))
		reserved_qty = max(flt(reserved.get(p.item)), 0)
		own_total = yard_qty + site_own + flt(inspection.get(p.item)) + flt(repair.get(p.item))
		rentable = own_total + site_cross + cross_idle
		on_hire = site_own + site_cross
		data.append(
			{
				"item_code": p.item,
				"item_name": p.item_name,
				"category": p.category,
				"uom": p.stock_uom,
				"yard_qty": yard_qty,
				"reserved_qty": reserved_qty,
				"available_qty": yard_qty - reserved_qty,
				"at_site_own": site_own,
				"at_site_cross_hire": site_cross,
				"cross_hire_not_at_site": cross_idle,
				"inspection_qty": flt(inspection.get(p.item)),
				"repair_qty": flt(repair.get(p.item)),
				"scrap_qty": flt(scrap.get(p.item)),
				"own_total": own_total,
				"utilization": (on_hire / rentable * 100) if rentable else 0,
			}
		)
	total_rentable = sum(d["own_total"] + d["at_site_cross_hire"] + d["cross_hire_not_at_site"] for d in data)
	total_on_hire = sum(d["at_site_own"] + d["at_site_cross_hire"] for d in data)
	summary = [
		{"label": _("Available in Rental Warehouses"), "value": sum(d["available_qty"] for d in data), "datatype": "Float", "indicator": "Green"},
		{"label": _("Reserved"), "value": sum(d["reserved_qty"] for d in data), "datatype": "Float", "indicator": "Orange"},
		{"label": _("On Hire"), "value": total_on_hire, "datatype": "Float", "indicator": "Blue"},
		{"label": _("Utilization %"), "value": (total_on_hire / total_rentable * 100) if total_rentable else 0, "datatype": "Percent", "indicator": "Blue"},
	]
	return get_columns(), data, None, None, summary


def selected_warehouses(filters, warehouses):
	out = list(warehouses)
	if filters.get("warehouse"):
		out = [w for w in out if w == filters.warehouse]
	if filters.get("location"):
		out = [w for w in out if (rw.location_of(w) or "") == filters.location]
	return out


def execute_by_warehouse(filters):
	"""One row per item and rental warehouse: in stock, reserved, available, and at sites from it."""
	rows = inventory.get_inventory({k: filters.get(k) for k in ("item_code", "category", "warehouse", "location", "ownership", "supplier")})
	data = {}
	for r in rows:
		if not r.warehouse:
			continue
		row = data.setdefault((r.item_code, r.warehouse), frappe._dict(
			item_code=r.item_code, item_name=r.item_name, category=r.category, uom=r.uom, warehouse=r.warehouse,
			location=r.location, ownership=r.ownership, in_stock=0, reserved_qty=0, available_qty=0, at_site=0,
			in_custody=0, workshop=0))
		if r.stock_status == "Available":
			row.available_qty += r.qty
			row.in_stock += r.qty
		elif r.stock_status == "Reserved":
			row.reserved_qty += r.qty
			row.in_stock += r.qty
		elif r.stock_status == "At Site":
			row.at_site += r.qty
		elif r.stock_status == "In Custody":
			row.in_custody += r.qty
			row.in_stock += r.qty
		else:
			row.workshop += r.qty
			row.in_stock += r.qty
	def qty(label, fieldname, width=105):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "width": width}

	columns = [
		{"label": _("Location"), "fieldname": "location", "width": 110},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
		{"label": _("Ownership"), "fieldname": "ownership", "width": 95},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 180},
		{"label": _("UOM"), "fieldname": "uom", "width": 60},
		qty(_("In Warehouse"), "in_stock"),
		qty(_("Reserved"), "reserved_qty"),
		qty(_("Available"), "available_qty"),
		qty(_("Cross Hire in Custody"), "in_custody", 140),
		qty(_("Inspection / Repair / Scrap"), "workshop", 160),
		qty(_("At Sites (Delivered From Here)"), "at_site", 170),
	]
	out = sorted(data.values(), key=lambda r: (r.location or "~", r.warehouse, r.item_code))
	summary = [
		{"label": _("Available"), "value": sum(r.available_qty for r in out), "datatype": "Float", "indicator": "Green"},
		{"label": _("Reserved"), "value": sum(r.reserved_qty for r in out), "datatype": "Float", "indicator": "Orange"},
		{"label": _("At Sites"), "value": sum(r.at_site for r in out), "datatype": "Float", "indicator": "Blue"},
		{"label": _("Cross Hire in Custody"), "value": sum(r.in_custody for r in out), "datatype": "Float", "indicator": "Purple"},
	]
	return columns, out, None, None, summary


def get_columns():
	def qty(label, fieldname, width=105):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "width": width}

	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 190},
		{"label": _("Category"), "fieldname": "category", "width": 110},
		{"label": _("UOM"), "fieldname": "uom", "width": 60},
		qty(_("In Rental Warehouses"), "yard_qty", 140),
		qty(_("Reserved"), "reserved_qty"),
		qty(_("Available"), "available_qty"),
		qty(_("At Sites (Own)"), "at_site_own", 115),
		qty(_("At Sites (Cross Hire)"), "at_site_cross_hire", 140),
		qty(_("Cross Hire Not at Site"), "cross_hire_not_at_site", 150),
		qty(_("Under Inspection"), "inspection_qty", 120),
		qty(_("In Repair"), "repair_qty"),
		qty(_("Scrap"), "scrap_qty", 80),
		qty(_("Own Rentable Total"), "own_total", 140),
		{"label": _("Utilization %"), "fieldname": "utilization", "fieldtype": "Percent", "width": 110},
	]
