"""Excess material per customer and item: received, returned to the customer, adjusted, still held."""
import frappe
from frappe import _
from frappe.utils import flt

from thinknxg_rental.thinknxg_rental.report.excess_material_register.excess_material_register import register_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	grouped = {}
	for r in register_rows(filters):
		key = (r.customer, r.item_code)
		g = grouped.setdefault(key, frappe._dict(customer=r.customer, customer_name=r.customer_name, item_code=r.item_code,
			item_name=r.item_name, uom=r.uom, registers=0, projects=set(), excess_qty=0, returned_to_customer_qty=0, adjusted_qty=0, available_qty=0, converted_qty=0))
		g.registers += 1
		if r.project:
			g.projects.add(r.project)
		for f in ("excess_qty", "returned_to_customer_qty", "adjusted_qty", "available_qty", "converted_qty"):
			g[f] += flt(r[f])
	rows = []
	for key in sorted(grouped, key=lambda k: (grouped[k].customer_name or k[0] or "", k[1])):
		g = grouped[key]
		g.projects = ", ".join(sorted(g.projects))
		rows.append(g)
	columns = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 170},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 170},
		{"label": _("UOM"), "fieldname": "uom", "width": 70},
		{"label": _("Projects"), "fieldname": "projects", "width": 160},
		{"label": _("Registers"), "fieldname": "registers", "fieldtype": "Int", "width": 90},
		{"label": _("Excess Received"), "fieldname": "excess_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Returned to Customer"), "fieldname": "returned_to_customer_qty", "fieldtype": "Float", "width": 130},
		{"label": _("Adjusted"), "fieldname": "adjusted_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Available"), "fieldname": "available_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Converted to Rental Stock"), "fieldname": "converted_qty", "fieldtype": "Float", "width": 130},
	]
	return columns, rows
