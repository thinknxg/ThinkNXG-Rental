import frappe
from frappe import _
from frappe.utils import flt

from thinknxg_rental.services.utils import get_settings


def execute(filters=None):
	filters = frappe._dict(filters or {})
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

	def bins(warehouse):
		if not warehouse:
			return {}
		return dict(
			frappe.get_all(
				"Bin", filters={"warehouse": warehouse, "item_code": ["in", items]}, fields=["item_code", "actual_qty"], as_list=True
			)
		)

	yard, inspection, repair, scrap = (
		bins(settings.rental_yard_warehouse),
		bins(settings.inspection_warehouse),
		bins(settings.repair_warehouse),
		bins(settings.scrap_warehouse),
	)
	reserved = dict(
		frappe.db.sql(
			"""
			select ri.item_code, sum(ri.reserved_qty - ri.dispatched_qty - ri.released_qty)
			from `tabRental Material Reservation Item` ri
			inner join `tabRental Material Reservation` r on r.name = ri.parent
			where r.docstatus = 1 and r.status not in ('Released', 'Dispatched')
			group by ri.item_code
			"""
		)
	)
	ledger = {}
	for r in frappe.db.sql(
		"""select item_code, position_type, ownership, sum(qty) as qty
		from `tabRental Ownership Ledger` group by item_code, position_type, ownership""",
		as_dict=True,
	):
		ledger[(r.item_code, r.position_type, r.ownership)] = flt(r.qty)

	data = []
	for p in profiles:
		site_own = ledger.get((p.item, "At Site", "Own"), 0)
		site_cross = ledger.get((p.item, "At Site", "Cross Hire"), 0)
		custody = ledger.get((p.item, "Cross Hire Custody", "Cross Hire"), 0)
		yard_qty = flt(yard.get(p.item))
		reserved_qty = max(flt(reserved.get(p.item)), 0)
		own_total = yard_qty + site_own + flt(inspection.get(p.item)) + flt(repair.get(p.item))
		rentable = own_total + custody
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
				"cross_hire_not_at_site": custody - site_cross,
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
		{"label": _("Available in Yard"), "value": sum(d["available_qty"] for d in data), "datatype": "Float", "indicator": "Green"},
		{"label": _("Reserved"), "value": sum(d["reserved_qty"] for d in data), "datatype": "Float", "indicator": "Orange"},
		{"label": _("On Hire"), "value": total_on_hire, "datatype": "Float", "indicator": "Blue"},
		{"label": _("Utilization %"), "value": (total_on_hire / total_rentable * 100) if total_rentable else 0, "datatype": "Percent", "indicator": "Blue"},
	]
	return get_columns(), data, None, None, summary


def get_columns():
	def qty(label, fieldname, width=105):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "width": width}

	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 190},
		{"label": _("Category"), "fieldname": "category", "width": 110},
		{"label": _("UOM"), "fieldname": "uom", "width": 60},
		qty(_("Yard Stock"), "yard_qty"),
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
