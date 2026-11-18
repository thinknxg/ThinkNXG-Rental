"""Material each customer still owes: delivered less returned, lost and adjusted, per contract and item."""
import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = ["l.position_type = 'At Site'"], {}
	for field in ("company", "customer", "project", "rental_contract", "item_code", "rental_site"):
		if filters.get(field):
			conditions.append(f"l.{field} = %({field})s")
			values[field] = filters[field]
	rows = frappe.db.sql(
		f"""select l.customer, max(c.customer_name) as customer_name, max(c.project) as project, l.rental_contract,
			max(c.rental_site) as rental_site, l.item_code, max(i.item_name) as item_name, max(i.stock_uom) as uom, l.ownership,
			sum(case when l.movement_type = 'Dispatch' then l.qty else 0 end) as delivered_qty,
			-sum(case when l.movement_type = 'Return' then l.qty else 0 end) as returned_qty,
			-sum(case when l.movement_type = 'Loss' then l.qty else 0 end) as lost_qty,
			-sum(case when l.movement_type = 'Adjustment' then l.qty else 0 end) as adjusted_qty,
			sum(l.qty) as outstanding_qty,
			max(case when l.movement_type = 'Dispatch' then l.posting_date end) as last_delivery,
			max(c.end_date) as end_date
		from `tabRental Ownership Ledger` l
		inner join `tabRental Contract` c on c.name = l.rental_contract
		left join `tabItem` i on i.name = l.item_code
		where {" and ".join(conditions)}
		group by l.customer, l.rental_contract, l.item_code, l.ownership
		having sum(l.qty) > 0
		order by max(c.customer_name), l.rental_contract, l.item_code""",
		values, as_dict=True,
	)
	excess = {}
	if rows:
		for r in frappe.db.sql(
			"""select customer, ifnull(project, '') as project, sum(available_qty) as qty from `tabExcess Material Register`
			where status != 'Cancelled' and customer in %(c)s group by customer, ifnull(project, '')""",
			{"c": tuple({r.customer for r in rows})}, as_dict=True,
		):
			excess[(r.customer, r.project)] = flt(r.qty)
	today = nowdate()
	for r in rows:
		r.excess_available_qty = excess.get((r.customer, r.project or ""), 0)
		r.days_overdue = max(date_diff(today, r.end_date), 0) if r.end_date else 0
	columns = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 120},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 160},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 120},
		{"label": _("Contract"), "fieldname": "rental_contract", "fieldtype": "Link", "options": "Rental Contract", "width": 140},
		{"label": _("Site"), "fieldname": "rental_site", "fieldtype": "Link", "options": "Rental Site", "width": 130},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 160},
		{"label": _("UOM"), "fieldname": "uom", "width": 70},
		{"label": _("Ownership"), "fieldname": "ownership", "width": 95},
		{"label": _("Delivered"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Returned"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Lost"), "fieldname": "lost_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Adjusted"), "fieldname": "adjusted_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Outstanding"), "fieldname": "outstanding_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Customer Excess Available (Project)"), "fieldname": "excess_available_qty", "fieldtype": "Float", "width": 150},
		{"label": _("Last Delivery"), "fieldname": "last_delivery", "fieldtype": "Date", "width": 100},
		{"label": _("Contract End"), "fieldname": "end_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 90},
	]
	return columns, rows
