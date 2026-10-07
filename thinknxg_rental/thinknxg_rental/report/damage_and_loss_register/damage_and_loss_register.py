import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = ["s.docstatus = 1"], {}
	for field in ("company", "customer", "rental_contract"):
		if filters.get(field):
			conditions.append(f"s.{field} = %({field})s")
			values[field] = filters[field]
	if filters.get("from_date"):
		conditions.append("s.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("s.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("classification"):
		conditions.append("si.classification = %(classification)s")
		values["classification"] = filters.classification
	rows = frappe.db.sql(
		f"""
		select s.posting_date, s.name as settlement, s.customer, s.customer_name, s.rental_contract, s.hire_off_hire_note,
			si.item_code, si.item_name, si.ownership, si.classification, si.qty, si.rate, si.liability_percent,
			si.salvage_value, si.amount, s.status, s.sales_invoice
		from `tabRental Damage Settlement Item` si
		inner join `tabRental Damage Settlement` s on s.name = si.parent
		where {" and ".join(conditions)}
		order by s.posting_date desc, s.name, si.idx
		""",
		values,
		as_dict=True,
	)
	columns = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Settlement"), "fieldname": "settlement", "fieldtype": "Link", "options": "Rental Damage Settlement", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 160},
		{"label": _("Contract"), "fieldname": "rental_contract", "fieldtype": "Link", "options": "Rental Contract", "width": 140},
		{"label": _("Off-Hire Note"), "fieldname": "hire_off_hire_note", "fieldtype": "Link", "options": "Hire Off-Hire Note", "width": 140},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 170},
		{"label": _("Ownership"), "fieldname": "ownership", "width": 95},
		{"label": _("Classification"), "fieldname": "classification", "width": 110},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		{"label": _("Charge per Unit"), "fieldname": "rate", "fieldtype": "Currency", "width": 120},
		{"label": _("Liability %"), "fieldname": "liability_percent", "fieldtype": "Percent", "width": 95},
		{"label": _("Salvage"), "fieldname": "salvage_value", "fieldtype": "Currency", "width": 100},
		{"label": _("Recoverable Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 150},
		{"label": _("Status"), "fieldname": "status", "width": 100},
		{"label": _("Sales Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
	]
	return columns, rows
