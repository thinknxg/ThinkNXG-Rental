import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = ["l.position_type = 'At Site'"], {}
	for field in ("company", "customer", "rental_contract", "rental_site", "item_code", "ownership", "supplier", "project"):
		if filters.get(field):
			conditions.append(f"l.{field} = %({field})s")
			values[field] = filters[field]
	if filters.get("as_on_date"):
		conditions.append("l.posting_date <= %(as_on_date)s")
		values["as_on_date"] = filters.as_on_date
	rows = frappe.db.sql(
		f"""
		select l.customer, c.customer_name, l.rental_site, l.project, l.rental_contract, l.item_code, i.item_name,
			i.stock_uom as uom, l.ownership, l.supplier, l.cross_hire_order, l.source_type, l.source_document,
			sum(l.qty) as qty,
			min(case when l.movement_type = 'Dispatch' then l.posting_date end) as first_dispatch,
			ifnull(p.replacement_value, 0) as replacement_rate
		from `tabRental Ownership Ledger` l
		left join `tabItem` i on i.name = l.item_code
		left join `tabCustomer` c on c.name = l.customer
		left join `tabRental Item Profile` p on p.name = l.item_code
		where {" and ".join(conditions)}
		group by l.customer, c.customer_name, l.rental_site, l.project, l.rental_contract, l.item_code, i.item_name,
			i.stock_uom, l.ownership, l.supplier, l.cross_hire_order, l.source_type, l.source_document, p.replacement_value
		having sum(l.qty) > 0
		order by l.customer, l.rental_site, l.rental_contract, l.item_code, l.ownership
		""",
		values,
		as_dict=True,
	)
	as_on = filters.get("as_on_date") or nowdate()
	for r in rows:
		r.days_at_site = date_diff(as_on, r.first_dispatch) + 1 if r.first_dispatch else 0
		r.replacement_value = flt(r.qty) * flt(r.replacement_rate)
	columns = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 160},
		{"label": _("Site"), "fieldname": "rental_site", "fieldtype": "Link", "options": "Rental Site", "width": 140},
		{"label": _("Contract"), "fieldname": "rental_contract", "fieldtype": "Link", "options": "Rental Contract", "width": 140},
		{"label": _("Source Type"), "fieldname": "source_type", "width": 150},
		{"label": _("Source"), "fieldname": "source_document", "fieldtype": "Dynamic Link", "options": "source_type", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 180},
		{"label": _("UOM"), "fieldname": "uom", "width": 60},
		{"label": _("Ownership"), "fieldname": "ownership", "width": 95},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 130},
		{"label": _("Cross Hire Order"), "fieldname": "cross_hire_order", "fieldtype": "Link", "options": "Cross Hire Order", "width": 140},
		{"label": _("Qty at Site"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("First Dispatch"), "fieldname": "first_dispatch", "fieldtype": "Date", "width": 105},
		{"label": _("Days at Site"), "fieldname": "days_at_site", "fieldtype": "Int", "width": 95},
		{"label": _("Replacement Value"), "fieldname": "replacement_value", "fieldtype": "Currency", "width": 140},
	]
	own = sum(flt(r.qty) for r in rows if r.ownership == "Own")
	cross = sum(flt(r.qty) for r in rows if r.ownership == "Cross Hire")
	summary = [
		{"label": _("Own Material at Sites"), "value": own, "datatype": "Float", "indicator": "Blue"},
		{"label": _("Cross-Hired Material at Sites"), "value": cross, "datatype": "Float", "indicator": "Orange"},
		{"label": _("Replacement Value at Sites"), "value": sum(flt(r.replacement_value) for r in rows), "datatype": "Currency", "indicator": "Green"},
	]
	return columns, rows, None, None, summary
