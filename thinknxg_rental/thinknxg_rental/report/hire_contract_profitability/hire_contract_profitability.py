import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	"""Gross contribution per contract = rental revenue + damage recovery - cross hire supplier cost."""
	filters = frappe._dict(filters or {})
	contract_filters = {"docstatus": 1}
	for field in ("company", "customer", "status"):
		if filters.get(field):
			contract_filters[field] = filters[field]
	contracts = frappe.get_all(
		"Hire Order Contract",
		filters=contract_filters,
		fields=["name", "customer", "customer_name", "rental_site", "status", "start_date", "end_date"],
		order_by="start_date desc",
	)
	date_cond, values = "", {}
	if filters.get("from_date"):
		date_cond += " and posting_date >= %(from_date)s"
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		date_cond += " and posting_date <= %(to_date)s"
		values["to_date"] = filters.to_date

	revenue, recovery = {}, {}
	for r in frappe.db.sql(
		f"""
		select nxg_hire_contract as contract,
			sum(case when ifnull(nxg_rental_damage_settlement, '') = '' then base_net_total else 0 end) as rental,
			sum(case when ifnull(nxg_rental_damage_settlement, '') != '' then base_net_total else 0 end) as damage
		from `tabSales Invoice`
		where docstatus = 1 and ifnull(nxg_hire_contract, '') != '' {date_cond}
		group by nxg_hire_contract
		""",
		values,
		as_dict=True,
	):
		revenue[r.contract], recovery[r.contract] = flt(r.rental), flt(r.damage)

	cost = dict(
		frappe.db.sql(
			f"""
			select o.hire_contract, sum(pi.base_net_total)
			from `tabPurchase Invoice` pi
			inner join `tabCross Hire Order` o on o.name = pi.nxg_cross_hire_order
			where pi.docstatus = 1 and ifnull(o.hire_contract, '') != '' {date_cond.replace("posting_date", "pi.posting_date")}
			group by o.hire_contract
			""",
			values,
		)
	)
	data = []
	for c in contracts:
		rental, damage, cross = revenue.get(c.name, 0), recovery.get(c.name, 0), flt(cost.get(c.name))
		if not (rental or damage or cross) and not filters.get("show_zero"):
			continue
		contribution = rental + damage - cross
		c.update(
			{
				"hire_contract": c.name,
				"rental_revenue": rental,
				"damage_recovery": damage,
				"cross_hire_cost": cross,
				"gross_contribution": contribution,
				"margin": (contribution / (rental + damage) * 100) if (rental + damage) else 0,
			}
		)
		data.append(c)
	columns = [
		{"label": _("Contract"), "fieldname": "hire_contract", "fieldtype": "Link", "options": "Hire Order Contract", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 170},
		{"label": _("Site"), "fieldname": "rental_site", "fieldtype": "Link", "options": "Rental Site", "width": 140},
		{"label": _("Status"), "fieldname": "status", "width": 90},
		{"label": _("Start"), "fieldname": "start_date", "fieldtype": "Date", "width": 100},
		{"label": _("End"), "fieldname": "end_date", "fieldtype": "Date", "width": 100},
		{"label": _("Rental Revenue"), "fieldname": "rental_revenue", "fieldtype": "Currency", "width": 140},
		{"label": _("Damage / Loss Recovery"), "fieldname": "damage_recovery", "fieldtype": "Currency", "width": 170},
		{"label": _("Cross Hire Cost"), "fieldname": "cross_hire_cost", "fieldtype": "Currency", "width": 140},
		{"label": _("Gross Contribution"), "fieldname": "gross_contribution", "fieldtype": "Currency", "width": 150},
		{"label": _("Margin %"), "fieldname": "margin", "fieldtype": "Percent", "width": 95},
	]
	return columns, data
