import frappe
from frappe import _
from frappe.utils import date_diff, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = ["o.docstatus = 1"], {}
	for field in ("company", "supplier", "hire_contract"):
		if filters.get(field):
			conditions.append(f"o.{field} = %({field})s")
			values[field] = filters[field]
	if filters.get("item_code"):
		conditions.append("oi.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	if not filters.get("include_closed"):
		conditions.append("(oi.on_hire_qty > 0 or o.status = 'To Receive')")
	rows = frappe.db.sql(
		f"""
		select o.supplier, o.supplier_name, o.name as cross_hire_order, o.purchase_order, o.status, o.hire_contract,
			o.customer, o.rental_site, o.hire_from, o.expected_return_date, oi.item_code, oi.item_name, oi.qty,
			oi.received_qty, oi.returned_qty, oi.lost_qty, oi.on_hire_qty, oi.rate, oi.rate_basis,
			(select ifnull(sum(l.qty), 0) from `tabRental Ownership Ledger` l
				where l.position_type = 'At Site' and l.cross_hire_order = o.name and l.item_code = oi.item_code) as at_site_qty
		from `tabCross Hire Order Item` oi
		inner join `tabCross Hire Order` o on o.name = oi.parent
		where {" and ".join(conditions)}
		order by o.supplier, o.name, oi.idx
		""",
		values,
		as_dict=True,
	)
	today = nowdate()
	for r in rows:
		r.in_yard_qty = flt(r.on_hire_qty) - flt(r.at_site_qty)
		r.overdue_days = max(date_diff(today, r.expected_return_date), 0) if flt(r.on_hire_qty) > 0 else 0

	def qty(label, fieldname, width=95):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "width": width}

	columns = [
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 130},
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "width": 150},
		{"label": _("Cross Hire Order"), "fieldname": "cross_hire_order", "fieldtype": "Link", "options": "Cross Hire Order", "width": 140},
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 140},
		{"label": _("Status"), "fieldname": "status", "width": 120},
		{"label": _("Customer Contract"), "fieldname": "hire_contract", "fieldtype": "Link", "options": "Hire Order Contract", "width": 140},
		{"label": _("Site"), "fieldname": "rental_site", "fieldtype": "Link", "options": "Rental Site", "width": 130},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 170},
		qty(_("Ordered"), "qty"),
		qty(_("Received"), "received_qty"),
		qty(_("Returned"), "returned_qty"),
		qty(_("Lost"), "lost_qty", 70),
		qty(_("On Hire"), "on_hire_qty"),
		qty(_("At Customer Site"), "at_site_qty", 125),
		qty(_("Not at Site"), "in_yard_qty"),
		{"label": _("Hire From"), "fieldname": "hire_from", "fieldtype": "Date", "width": 100},
		{"label": _("Due for Return"), "fieldname": "expected_return_date", "fieldtype": "Date", "width": 110},
		{"label": _("Overdue Days"), "fieldname": "overdue_days", "fieldtype": "Int", "width": 100},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 90},
		{"label": _("Basis"), "fieldname": "rate_basis", "width": 80},
	]
	return columns, rows
