"""Recurring rental billing.

Billing is in arrears and movement-based: every day of a period is billed for the quantity
that was actually on hire that day, taken from the Rental Ownership Ledger. Partial returns
therefore reduce the bill from the day after their last billable date with no manual proration.
"""
import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, flt, formatdate, get_last_day, getdate, nowdate

from thinknxg_rental.services import ledger
from thinknxg_rental.services.utils import BASIS_FACTOR, BASIS_UOM, as_system, billable_units, get_settings, require_setting


def get_period_end(contract, from_date):
	from_date = getdate(from_date)
	cycle = contract.billing_cycle or "Monthly"
	if cycle == "Daily":
		return from_date
	if cycle == "Weekly":
		return add_days(from_date, 6)
	if cycle == "Custom":
		return add_days(from_date, max(cint(contract.billing_interval_days), 1) - 1)
	if cint(contract.align_to_calendar_month):
		return getdate(get_last_day(from_date))
	return add_days(add_months(from_date, 1), -1)


def compute_lines(contract, from_date, to_date):
	"""Billing lines for a contract between two dates (inclusive)."""
	month_basis = get_settings().month_basis
	rates = {d.item_code: d for d in contract.items}
	lines = []
	segments = ledger.get_segments(from_date, to_date, ledger.AT_SITE, rental_contract=contract.name)
	for item_code in sorted(segments):
		row = rates.get(item_code)
		if not row:
			continue
		basis = row.rate_basis or "Monthly"
		for seg_from, seg_to, qty in segments[item_code]:
			units = flt(billable_units(qty, seg_from, seg_to, basis, month_basis), 3)
			lines.append(
				{
					"item_code": item_code,
					"item_name": row.item_name,
					"from_date": seg_from,
					"to_date": seg_to,
					"days": date_diff(seg_to, seg_from) + 1,
					"qty": qty,
					"rate_basis": basis,
					"rate": flt(row.rate),
					"billable_units": units,
					"amount": flt(units * flt(row.rate), 3),
				}
			)
	return lines


def get_last_billable_day(rental_contract):
	last = frappe.db.sql(
		"select max(billing_date) from `tabRental Ownership Ledger` where position_type = %s and rental_contract = %s",
		(ledger.AT_SITE, rental_contract),
	)[0][0]
	return add_days(getdate(last), -1) if last else None


@frappe.whitelist()
def generate_billing(rental_contract: str, upto_date: str | None = None, only_complete: int = 0):
	"""Create billing schedules (and Sales Invoices) for every unbilled period up to `upto_date`.

	only_complete=1 (scheduler) bills whole periods only, except that a fully off-hired
	contract is billed up to its last billable day straight away.
	"""
	contract = frappe.get_doc("Rental Contract", rental_contract)
	contract.check_permission("write")
	if contract.docstatus != 1:
		frappe.throw(_("Contract {0} is not submitted").format(rental_contract))
	if contract.contract_type == "Job Type Contract" or not contract.billing_start_date:
		return []

	limit = getdate(upto_date) if upto_date else add_days(getdate(nowdate()), -1)
	off_hired = flt(contract.total_at_site_qty) <= 0
	if off_hired:
		last_day = get_last_billable_day(rental_contract)
		if last_day:
			limit = min(limit, getdate(last_day))

	from_date = add_days(contract.last_billed_upto, 1) if contract.last_billed_upto else getdate(contract.billing_start_date)
	from_date = getdate(from_date)
	created, guard = [], 0
	while from_date <= limit and guard < 120:
		guard += 1
		period_end = getdate(get_period_end(contract, from_date))
		if period_end > limit:
			if cint(only_complete) and not off_hired:
				break
			period_end = limit
		lines = compute_lines(contract, from_date, period_end)
		if lines:
			schedule = frappe.new_doc("Rental Billing Schedule")
			schedule.update(
				{
					"company": contract.company,
					"rental_contract": contract.name,
					"posting_date": nowdate(),
					"from_date": from_date,
					"to_date": period_end,
				}
			)
			for line in lines:
				schedule.append("items", line)
			schedule.flags.ignore_permissions = True
			schedule.insert()
			schedule.submit()
			make_sales_invoice(schedule.name)
			created.append(schedule.name)
		else:
			set_billing_pointers(contract, period_end)
		contract.reload()
		from_date = add_days(period_end, 1)
	return created


def set_billing_pointers(contract, billed_upto):
	next_date = add_days(get_period_end(contract, add_days(billed_upto, 1)), 1) if billed_upto else None
	contract.db_set({"last_billed_upto": billed_upto, "next_billing_date": next_date}, update_modified=False)


def get_default_taxes(doctype, company):
	return frappe.db.get_value(doctype, {"company": company, "is_default": 1, "disabled": 0}, "name")


def append_taxes(invoice, template_doctype, template):
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	template = template or get_default_taxes(template_doctype, invoice.company)
	if not template:
		return
	invoice.taxes_and_charges = template
	for tax in get_taxes_and_charges(template_doctype, template) or []:
		invoice.append("taxes", tax)


@frappe.whitelist()
def make_sales_invoice(schedule: str):
	doc = frappe.get_doc("Rental Billing Schedule", schedule)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the billing schedule first"))
	if doc.sales_invoice:
		frappe.throw(_("Sales Invoice {0} already exists for this schedule").format(doc.sales_invoice))
	settings = get_settings()
	charge_item = require_setting("rental_charge_item")
	contract = frappe.get_doc("Rental Contract", doc.rental_contract)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": doc.company,
			"customer": contract.customer,
			"posting_date": nowdate(),
			"project": contract.project,
			"cost_center": contract.cost_center,
			"payment_terms_template": contract.payment_terms_template,
			"nxg_rental_contract": contract.name,
			"nxg_rental_billing_schedule": doc.name,
			"remarks": _("Rental charges {0} to {1} - Contract {2}, Site {3}").format(
				formatdate(doc.from_date), formatdate(doc.to_date), contract.name, contract.rental_site
			),
		}
	)
	for line in doc.items:
		si.append(
			"items",
			{
				"item_code": charge_item,
				"item_name": line.item_name,
				"description": _("{0}: {1} {2} on hire {3} to {4} ({5} days)").format(
					line.item_name, frappe.format_value(line.qty, {"fieldtype": "Float"}), _("units"),
					formatdate(line.from_date), formatdate(line.to_date), line.days,
				),
				"qty": line.billable_units,
				"uom": BASIS_UOM[line.rate_basis],
				"conversion_factor": BASIS_FACTOR[line.rate_basis],
				"rate": line.rate,
				"project": contract.project,
				"cost_center": contract.cost_center,
				"nxg_hire_item": line.item_code,
				"nxg_hire_from": line.from_date,
				"nxg_hire_to": line.to_date,
				"nxg_hire_days": line.days,
				"nxg_hire_qty": line.qty,
			},
		)
	append_taxes(si, "Sales Taxes and Charges Template", contract.taxes_and_charges)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
		doc.db_set("sales_invoice", si.name)
		if cint(settings.auto_submit_sales_invoice):
			si.submit()
	return si.name


def update_contract_billed_amount(rental_contract):
	total = frappe.db.sql(
		"""select sum(base_net_total) from `tabSales Invoice`
		where docstatus = 1 and nxg_rental_contract = %s
			and ifnull(nxg_rental_billing_schedule, '') != ''""",
		rental_contract,
	)[0][0]
	# Job (JCR) invoices are summed by row, so one combined invoice counts towards each contract it bills.
	total = flt(total) + flt(
		frappe.db.sql(
			"""select sum(it.base_net_amount) from `tabSales Invoice Item` it
			inner join `tabSales Invoice` si on si.name = it.parent
			where si.docstatus = 1 and ifnull(it.nxg_jcr_billing_schedule, '') != ''
				and it.nxg_jcr in (select name from `tabJob Completion Report` where rental_contract = %s)""",
			rental_contract,
		)[0][0]
	)
	frappe.db.set_value("Rental Contract", rental_contract, "total_billed_amount", flt(total), update_modified=False)


def run_daily_billing():
	"""Scheduler: bill every completed period for contracts with material on (or just off) hire."""
	if not cint(get_settings().auto_generate_billing):
		return
	contracts = frappe.get_all(
		"Rental Contract",
		filters={"docstatus": 1, "status": ["in", ["On Hire", "Off Hired"]], "contract_type": ["!=", "Job Type Contract"]},
		pluck="name",
	)
	for name in contracts:
		try:
			generate_billing(name, only_complete=1)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Rental billing failed for {name}", message=frappe.get_traceback())
