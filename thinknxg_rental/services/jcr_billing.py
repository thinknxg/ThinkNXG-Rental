"""Job Completion Report billing.

A JCR starts the contract clock on its erection date. The contract charge covers the included
days. Anything beyond that is excess, billed at each month end while the job is still standing
and up to the dismantle date once it is recorded. One JCR Billing Schedule row is kept per
period, so a period can never be invoiced twice.
"""
import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, get_last_day, getdate, nowdate

from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import as_system, billable_units, get_settings


def get_contract_end(erection_date, included_days):
	return add_days(getdate(erection_date), max(cint(included_days), 1) - 1)


def plan_periods(jcr, today=None):
	"""Every billing period of a JCR that is due as of `today`."""
	today = getdate(today or nowdate())
	erection = getdate(jcr.erection_date)
	contract_end = getdate(jcr.contract_end_date or get_contract_end(erection, jcr.included_days))
	dismantle = getdate(jcr.dismantle_date) if jcr.dismantle_date else None
	job_qty = flt(jcr.job_qty) or 1
	month_basis = get_settings().month_basis
	periods = []

	if jcr.contract_charge_billing == "At Contract End":
		contract_due = min(contract_end, dismantle) if dismantle else contract_end
	else:
		contract_due = erection
	if today >= contract_due:
		charge = flt(jcr.contract_rate) * job_qty
		periods.append(
			frappe._dict(
				period_from=erection, period_to=contract_end, billing_type="Contract",
				days=date_diff(contract_end, erection) + 1, contract_charge=charge, excess_charge=0, amount=charge,
			)
		)

	start = add_days(contract_end, 1)
	while not dismantle or dismantle >= start:
		period_to = getdate(get_last_day(start))
		final = bool(dismantle and dismantle <= period_to)
		if final:
			period_to = dismantle
		elif today <= period_to:
			break  # month still running and the job is still standing
		units = billable_units(job_qty, start, period_to, jcr.excess_rate_basis or "Daily", month_basis)
		charge = flt(units * flt(jcr.excess_rate), 3)
		periods.append(
			frappe._dict(
				period_from=start, period_to=period_to, billing_type="Final Excess" if final else "Excess",
				days=date_diff(period_to, start) + 1, contract_charge=0, excess_charge=charge, amount=charge,
			)
		)
		if final:
			break
		start = add_days(period_to, 1)
	return periods


def get_schedules(jcr_name):
	return frappe.get_all(
		"JCR Billing Schedule",
		filters={"jcr": jcr_name},
		fields=["name", "period_from", "period_to", "billing_type", "amount", "status", "billed", "sales_invoice"],
		order_by="period_from asc",
	)


@frappe.whitelist()
def generate_jcr_billing(jcr: str):
	"""Create the due JCR Billing Schedule rows and their Sales Invoices. Safe to run repeatedly."""
	doc = frappe.get_doc("Job Completion Report", jcr)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the JCR first"))
	existing = {getdate(s.period_from): s for s in get_schedules(doc.name)}
	created = []
	for p in plan_periods(doc):
		row = existing.get(getdate(p.period_from))
		if row:
			if getdate(row.period_to) != getdate(p.period_to) and row.status == "Pending" and not row.sales_invoice:
				# a month-end row that became the final period before it was invoiced
				frappe.db.set_value("JCR Billing Schedule", row.name, dict(p))
			if row.status == "Pending" and not row.sales_invoice:
				make_sales_invoice(row.name)
				created.append(row.name)
			continue
		schedule = frappe.new_doc("JCR Billing Schedule")
		schedule.update(p)
		schedule.update(
			{
				"jcr": doc.name,
				"rental_contract": doc.rental_contract,
				"hire_order_contract": doc.hire_order_contract,
				"customer": doc.customer,
				"job_type": doc.job_type,
				"company": doc.company,
				"status": "Pending" if flt(p.amount) > 0 else "No Charge",
			}
		)
		schedule.flags.ignore_permissions = True
		schedule.insert()
		if flt(p.amount) > 0:
			make_sales_invoice(schedule.name)
		created.append(schedule.name)
	update_jcr_progress(doc.name)
	return created


@frappe.whitelist()
def make_sales_invoice(schedule: str):
	row = frappe.get_doc("JCR Billing Schedule", schedule)
	row.check_permission("read")
	if row.sales_invoice:
		frappe.throw(_("Sales Invoice {0} already exists for this period").format(row.sales_invoice))
	if flt(row.amount) <= 0:
		frappe.throw(_("Nothing to invoice for this period"))
	jcr = frappe.get_doc("Job Completion Report", row.jcr)
	hoc = frappe.get_doc("Hire Order Contract", jcr.hire_order_contract)
	job_qty = flt(jcr.job_qty) or 1
	period = _("{0} to {1} ({2} days)").format(formatdate(row.period_from), formatdate(row.period_to), row.days)
	where = f" - {jcr.location}" if jcr.location else ""
	if row.billing_type == "Contract":
		description = _("Contract charge: {0}{1}, {2} included days, {3}").format(jcr.job_type_name, where, jcr.included_days, period)
	else:
		description = _("Excess charge: {0}{1}, {2}, at {3} per job ({4})").format(
			jcr.job_type_name, where, period, frappe.format_value(jcr.excess_rate, {"fieldtype": "Currency"}), jcr.excess_rate_basis
		)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": jcr.company,
			"customer": jcr.customer,
			"posting_date": nowdate(),
			"project": hoc.project,
			"cost_center": hoc.cost_center,
			"payment_terms_template": hoc.payment_terms_template,
			"nxg_rental_contract": jcr.rental_contract,
			"nxg_jcr": jcr.name,
			"nxg_jcr_billing_schedule": row.name,
			"remarks": _("{0} - JCR {1}, Hire Order Contract {2}").format(description, jcr.name, hoc.name),
		}
	)
	si.append(
		"items",
		{
			"item_code": jcr.job_type,
			"item_name": jcr.job_type_name,
			"description": description,
			"qty": job_qty,
			"rate": flt(row.amount) / job_qty,
			"project": hoc.project,
			"cost_center": hoc.cost_center,
		},
	)
	append_taxes(si, "Sales Taxes and Charges Template", hoc.taxes_and_charges)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
		frappe.db.set_value("JCR Billing Schedule", row.name, "sales_invoice", si.name)
		if cint(get_settings().auto_submit_sales_invoice):
			si.submit()
	return si.name


def update_jcr_progress(jcr_name):
	"""Recompute days, billed totals and status of a JCR (idempotent)."""
	doc = frappe.get_doc("Job Completion Report", jcr_name)
	if doc.docstatus != 1:
		return
	today = getdate(nowdate())
	erection = getdate(doc.erection_date)
	contract_end = getdate(doc.contract_end_date)
	upto = getdate(doc.dismantle_date) if doc.dismantle_date else max(today, erection)
	actual = max(date_diff(upto, erection) + 1, 0)
	excess = max(date_diff(upto, contract_end), 0)
	schedules = get_schedules(doc.name)
	settled = [s for s in schedules if s.status in ("Invoiced", "No Charge")]
	billed_amount = sum(flt(s.amount) for s in schedules if s.status == "Invoiced")
	billed_upto = max((getdate(s.period_to) for s in settled), default=None)

	if doc.dismantle_date:
		last_day = max(getdate(doc.dismantle_date), contract_end)
		contract_done = any(s.billing_type == "Contract" and s.status in ("Invoiced", "No Charge") for s in schedules)
		done = contract_done and billed_upto and billed_upto >= last_day and all(s.status != "Pending" for s in schedules)
		status = "Completed" if done else "Dismantled"
	else:
		status = "In Excess" if today > contract_end else "Within Contract"
	doc.db_set(
		{"actual_days": actual, "excess_days": excess, "billed_upto": billed_upto, "total_billed_amount": billed_amount, "status": status},
		update_modified=False,
	)
	doc.notify_update()


def run_daily_jcr_billing():
	"""Scheduler: month-end excess billing for every JCR that is still standing or not fully billed."""
	if not cint(get_settings().auto_generate_jcr_billing):
		return
	for name in frappe.get_all(
		"Job Completion Report", filters={"docstatus": 1, "status": ["not in", ["Completed", "Cancelled"]]}, pluck="name"
	):
		try:
			generate_jcr_billing(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"JCR billing failed for {name}", message=frappe.get_traceback())
