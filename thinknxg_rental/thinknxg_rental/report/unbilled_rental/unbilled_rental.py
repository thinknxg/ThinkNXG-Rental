import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from thinknxg_rental.services import billing


def execute(filters=None):
	filters = frappe._dict(filters or {})
	upto = getdate(filters.get("upto_date") or nowdate())
	contract_filters = {"docstatus": 1, "status": ["in", ["On Hire", "Off Hired"]]}
	for field in ("company", "customer"):
		if filters.get(field):
			contract_filters[field] = filters[field]
	data = []
	for name in frappe.get_all("Hire Order Contract", filters=contract_filters, pluck="name", order_by="next_billing_date asc"):
		contract = frappe.get_doc("Hire Order Contract", name)
		if not contract.billing_start_date:
			continue
		from_date = getdate(add_days(contract.last_billed_upto, 1) if contract.last_billed_upto else contract.billing_start_date)
		amount = 0
		if from_date <= upto:
			amount = sum(flt(line["amount"]) for line in billing.compute_lines(contract, from_date, upto))
		if not amount and not filters.get("show_zero"):
			continue
		data.append(
			{
				"hire_contract": contract.name,
				"customer": contract.customer,
				"customer_name": contract.customer_name,
				"rental_site": contract.rental_site,
				"status": contract.status,
				"billing_cycle": contract.billing_cycle,
				"last_billed_upto": contract.last_billed_upto,
				"unbilled_from": from_date,
				"next_billing_date": contract.next_billing_date,
				"overdue": 1 if contract.next_billing_date and getdate(contract.next_billing_date) <= getdate(nowdate()) else 0,
				"at_site_qty": contract.total_at_site_qty,
				"unbilled_amount": amount,
			}
		)
	columns = [
		{"label": _("Contract"), "fieldname": "hire_contract", "fieldtype": "Link", "options": "Hire Order Contract", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Customer Name"), "fieldname": "customer_name", "width": 170},
		{"label": _("Site"), "fieldname": "rental_site", "fieldtype": "Link", "options": "Rental Site", "width": 140},
		{"label": _("Status"), "fieldname": "status", "width": 90},
		{"label": _("Cycle"), "fieldname": "billing_cycle", "width": 80},
		{"label": _("Billed Upto"), "fieldname": "last_billed_upto", "fieldtype": "Date", "width": 105},
		{"label": _("Unbilled From"), "fieldname": "unbilled_from", "fieldtype": "Date", "width": 110},
		{"label": _("Next Billing Date"), "fieldname": "next_billing_date", "fieldtype": "Date", "width": 125},
		{"label": _("Billing Due"), "fieldname": "overdue", "fieldtype": "Check", "width": 90},
		{"label": _("Qty at Site"), "fieldname": "at_site_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Accrued Unbilled Amount"), "fieldname": "unbilled_amount", "fieldtype": "Currency", "width": 170},
	]
	return columns, data
