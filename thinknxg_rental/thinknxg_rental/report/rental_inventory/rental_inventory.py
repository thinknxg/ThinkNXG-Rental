"""Rental inventory by location and warehouse: own, reserved, at site, cross hire custody, workshop."""
from frappe import _
from frappe.utils import flt

from thinknxg_rental.services.inventory import STATUSES, get_inventory


def execute(filters=None):
	rows = get_inventory(filters)
	columns = [
		{"label": _("Location"), "fieldname": "location", "width": 120},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 180},
		{"label": _("UOM"), "fieldname": "uom", "width": 60},
		{"label": _("Ownership"), "fieldname": "ownership", "width": 95},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 130},
		{"label": _("Cross Hire Order"), "fieldname": "cross_hire_order", "fieldtype": "Link", "options": "Cross Hire Order", "width": 140},
		{"label": _("Stock Status"), "fieldname": "stock_status", "width": 120},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
	]
	totals = {}
	for r in rows:
		totals[r.stock_status] = totals.get(r.stock_status, 0) + flt(r.qty)
	indicators = {"Available": "Green", "Reserved": "Orange", "At Site": "Blue", "In Custody": "Purple"}
	summary = [
		{"label": _(st), "value": totals.get(st, 0), "datatype": "Float", "indicator": indicators.get(st, "Grey")}
		for st in STATUSES if st in totals or st in indicators
	]
	return columns, rows, None, None, summary
