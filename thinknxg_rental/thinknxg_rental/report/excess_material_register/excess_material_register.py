"""Every excess register: where the excess came from and what has become of it."""
import frappe
from frappe import _


def register_rows(filters, extra_conditions=()):
	conditions, values = ["r.status != 'Cancelled'" if filters.get("status") != "Cancelled" else "1=1"], {}
	for field in ("company", "customer", "project", "rental_contract", "item_code", "excess_category", "status"):
		if filters.get(field):
			conditions.append(f"r.{field} = %({field})s")
			values[field] = filters[field]
	if filters.get("from_date"):
		conditions.append("r.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("r.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("open_only"):
		conditions.append("r.available_qty > 0")
	conditions.extend(extra_conditions)
	return frappe.db.sql(
		f"""select r.name as register, r.posting_date, r.customer, r.customer_name, r.project, r.rental_contract,
			r.hire_off_hire_note, r.hire_delivery_order, r.item_code, r.item_name, r.uom, r.excess_category,
			r.delivered_qty, r.off_hire_returned_qty, r.excess_qty, r.returned_to_customer_qty, r.adjusted_qty, r.abandoned_qty, r.available_qty,
			r.converted_qty, r.convertible_qty,
			r.source_warehouse, r.excess_warehouse, r.stock_entry, r.status
		from `tabExcess Material Register` r
		where {" and ".join(conditions)}
		order by r.posting_date desc, r.name""",
		values, as_dict=True,
	)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"label": _("Excess Register"), "fieldname": "register", "fieldtype": "Link", "options": "Excess Material Register", "width": 140},
		{"label": _("Received On"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 150},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 120},
		{"label": _("Contract"), "fieldname": "rental_contract", "fieldtype": "Link", "options": "Rental Contract", "width": 140},
		{"label": _("Off-Hire Note"), "fieldname": "hire_off_hire_note", "fieldtype": "Link", "options": "Hire Off-Hire Note", "width": 140},
		{"label": _("Delivery Order"), "fieldname": "hire_delivery_order", "fieldtype": "Link", "options": "Hire Delivery Order", "width": 140},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 160},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Category"), "fieldname": "excess_category", "width": 180},
		{"label": _("Delivered on Contract"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Returned on Off-Hire"), "fieldname": "off_hire_returned_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Excess Received"), "fieldname": "excess_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Returned to Customer"), "fieldname": "returned_to_customer_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Adjusted"), "fieldname": "adjusted_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Abandoned by Customer"), "fieldname": "abandoned_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Available"), "fieldname": "available_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Converted to Rental Stock"), "fieldname": "converted_qty", "fieldtype": "Float", "width": 120},
		{"label": _("Available to Convert"), "fieldname": "convertible_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Source (Site) Warehouse"), "fieldname": "source_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 150},
		{"label": _("Excess Warehouse"), "fieldname": "excess_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 150},
		{"label": _("Stock Entry"), "fieldname": "stock_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 140},
		{"label": _("Status"), "fieldname": "status", "width": 110},
	]
	return columns, register_rows(filters)
