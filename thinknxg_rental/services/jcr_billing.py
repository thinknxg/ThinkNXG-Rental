"""Billing for single-line legacy JCRs and multi-line JCRs."""
import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, get_last_day, getdate, nowdate

from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import as_system, billable_units, get_settings


def get_contract_end(erection_date, included_days):
	return add_days(getdate(erection_date), max(cint(included_days), 1) - 1)


def _lines(jcr):
	"""Return billable JCR lines. New JCRs have child rows; old ones use the header fields."""
	if getattr(jcr, "items", None):
		return list(jcr.items)
	return [jcr]


def plan_periods(jcr, line=None, today=None):
	today = getdate(today or nowdate())
	line = line or jcr
	erection = getdate(line.erection_date)
	contract_end = getdate(line.contract_end_date or get_contract_end(erection, line.included_days))
	dismantle = getdate(line.dismantle_date) if line.dismantle_date else None
	job_qty = flt(line.job_qty) or 1
	month_basis = get_settings().month_basis
	periods = []

	if line.contract_charge_billing == "At Contract End":
		contract_due = min(contract_end, dismantle) if dismantle else contract_end
	else:
		contract_due = erection
	if today >= contract_due:
		charge = flt(line.contract_rate) * job_qty
		periods.append(frappe._dict(period_from=erection, period_to=contract_end, billing_type="Contract",
			days=date_diff(contract_end, erection) + 1, contract_charge=charge, excess_charge=0, amount=charge))

	start = add_days(contract_end, 1)
	while not dismantle or dismantle >= start:
		period_to = getdate(get_last_day(start))
		final = bool(dismantle and dismantle <= period_to)
		if final:
			period_to = dismantle
		elif today <= period_to:
			break
		units = billable_units(job_qty, start, period_to, line.excess_rate_basis or "Daily", month_basis)
		charge = flt(units * flt(line.excess_rate), 3)
		periods.append(frappe._dict(period_from=start, period_to=period_to,
			billing_type="Final Excess" if final else "Excess", days=date_diff(period_to, start) + 1,
			contract_charge=0, excess_charge=charge, amount=charge))
		if final:
			break
		start = add_days(period_to, 1)
	return periods


def get_schedules(jcr_name):
	return frappe.get_all("JCR Billing Schedule", filters={"jcr": jcr_name},
		fields=["name", "jcr_item", "period_from", "period_to", "billing_type", "amount", "status", "billed", "sales_invoice"],
		order_by="period_from asc, creation asc")


@frappe.whitelist()
def generate_jcr_billing(jcr: str):
	doc = frappe.get_doc("Job Completion Report", jcr)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the JCR first"))
	existing = {(getdate(s.period_from), s.jcr_item or ""): s for s in get_schedules(doc.name)}
	created = []
	for line in _lines(doc):
		for p in plan_periods(doc, line):
			key = (getdate(p.period_from), getattr(line, "name", ""))
			row = existing.get(key)
			if row:
				if getdate(row.period_to) != getdate(p.period_to) and row.status == "Pending" and not row.sales_invoice:
					frappe.db.set_value("JCR Billing Schedule", row.name, dict(p))
				if row.status == "Pending" and not row.sales_invoice:
					make_sales_invoice(row.name)
					created.append(row.name)
				continue
			schedule = frappe.new_doc("JCR Billing Schedule")
			schedule.update(p)
			schedule.update({"jcr": doc.name, "jcr_item": getattr(line, "name", ""), "rental_contract": doc.rental_contract,
			"hire_order_contract": doc.hire_order_contract, "customer": doc.customer, "job_type": line.job_type,
			"company": doc.company, "status": "Pending" if flt(p.amount) > 0 else "No Charge"})
			schedule.flags.ignore_permissions = True
			schedule.insert()
		if flt(p.amount) > 0:
			make_sales_invoice(schedule.name)
		created.append(schedule.name)
	update_jcr_progress(doc.name)
	return created


@frappe.whitelist()
def generate_all_jcr_billing(hire_order_contract: str):
	hoc = frappe.get_doc("Hire Order Contract", hire_order_contract)
	hoc.check_permission("read")
	if hoc.docstatus != 1:
		frappe.throw(_("Hire Order Contract {0} must be submitted before billing JCRs.").format(hoc.name))
	names = frappe.get_all("Job Completion Report", filters={"hire_order_contract": hoc.name, "docstatus": 1}, pluck="name", order_by="creation asc")	
	return [{"jcr": name, "schedules": generate_jcr_billing(name)} for name in names]


def _line_for_schedule(jcr, schedule):
	if schedule.jcr_item and jcr.items:
		line = next((d for d in jcr.items if d.name == schedule.jcr_item), None)
		if line:
			return line
	return jcr


def make_sales_invoice(schedule: str):
	row = frappe.get_doc("JCR Billing Schedule", schedule)
	row.check_permission("read")
	if row.sales_invoice:
		frappe.throw(_("Sales Invoice {0} already exists for this period").format(row.sales_invoice))
	if flt(row.amount) <= 0:
		frappe.throw(_("Nothing to invoice for this period"))
	jcr = frappe.get_doc("Job Completion Report", row.jcr)
	line = _line_for_schedule(jcr, row)
	hoc = frappe.get_doc("Hire Order Contract", jcr.hire_order_contract)
	job_qty = flt(line.job_qty) or 1
	period = _("{0} to {1} ({2} days)").format(formatdate(row.period_from), formatdate(row.period_to), row.days)
	where = f" - {line.location}" if line.location else ""
	if row.billing_type == "Contract":
		description = _("Contract charge: {0}{1}, {2} included days, {3}").format(line.job_type_name or line.job_type, where, line.included_days, period)
	else:
		description = _("Excess charge: {0}{1}, {2}, at {3} per job ({4})").format(line.job_type_name or line.job_type, where, period, frappe.format_value(line.excess_rate, {"fieldtype": "Currency"}), line.excess_rate_basis)
	si = frappe.new_doc("Sales Invoice")
	si.update({"company": jcr.company, "customer": jcr.customer, "posting_date": nowdate(), "project": hoc.project,
		"cost_center": hoc.cost_center, "payment_terms_template": hoc.payment_terms_template,
		"nxg_rental_contract": jcr.rental_contract, "nxg_jcr": jcr.name, "nxg_jcr_billing_schedule": row.name,
		"remarks": _("{0} - JCR {1}, Hire Order Contract {2}").format(description, jcr.name, hoc.name)})
	si.append("items", {"item_code": line.job_type, "item_name": line.job_type_name or line.job_type, "description": description,
		"qty": job_qty if job_qty == int(job_qty) else 1, "rate": flt(row.amount) / (job_qty if job_qty == int(job_qty) else 1),
		"project": hoc.project, "cost_center": hoc.cost_center})
	append_taxes(si, "Sales Taxes and Charges Template", hoc.taxes_and_charges)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
		frappe.db.set_value("JCR Billing Schedule", row.name, {"sales_invoice": si.name, "status": "Invoiced", "billed": 1})
		if cint(get_settings().auto_submit_sales_invoice):
			si.submit()
	return si.name


def update_jcr_progress(jcr_name):
	doc = frappe.get_doc("Job Completion Report", jcr_name)
	if doc.docstatus != 1:
		return
	today = getdate(nowdate())
	schedules = get_schedules(doc.name)
	billed_amount = sum(flt(s.amount) for s in schedules if s.status == "Invoiced")
	billed_upto = max((getdate(s.period_to) for s in schedules if s.status in ("Invoiced", "No Charge")), default=None)
	if doc.items:
		statuses=[]
		for line in doc.items:
			end=getdate(line.contract_end_date)
			upto=getdate(line.dismantle_date) if line.dismantle_date else max(today,getdate(line.erection_date))
			actual_days=max(date_diff(upto,line.erection_date)+1,0)
			excess_days=max(date_diff(upto,end),0)
			ls=[s for s in schedules if (s.jcr_item or "")==line.name]
			billed_line_upto=max((getdate(s.period_to) for s in ls if s.status in ("Invoiced","No Charge")),default=None)
			total_line_billed=sum(flt(s.amount) for s in ls if s.status=="Invoiced")
			if line.dismantle_date:
				contract_done=any(s.billing_type=="Contract" and s.status in ("Invoiced","No Charge") for s in ls)
				done=contract_done and billed_line_upto and billed_line_upto>=getdate(line.dismantle_date) and all(s.status!="Pending" for s in ls)
				line_status="Completed" if done else "Dismantled"
			else:
				line_status="In Excess" if today>getdate(line.contract_end_date) else "Within Contract"
			statuses.append(line_status)
			frappe.db.set_value("JCR Item", line.name, {"actual_days":actual_days, "excess_days":excess_days, "billed_upto":billed_line_upto, "total_billed_amount":total_line_billed, "status":line_status}, update_modified=False)
		all_done=bool(statuses) and all(x=="Completed" for x in statuses)
		status="Completed" if all_done else ("In Excess" if any(x=="In Excess" for x in statuses) else ("Dismantled" if any(x=="Dismantled" for x in statuses) else "Within Contract"))
		actual=max((flt(x.actual_days) for x in doc.items),default=0)
		excess=max((flt(x.excess_days) for x in doc.items),default=0)
	else:
		erection=getdate(doc.erection_date); end=getdate(doc.contract_end_date); upto=getdate(doc.dismantle_date) if doc.dismantle_date else max(today,erection)
		actual=max(date_diff(upto,erection)+1,0); excess=max(date_diff(upto,end),0)
		settled=[s for s in schedules if s.status in ("Invoiced","No Charge")]
		if doc.dismantle_date:
			contract_done=any(s.billing_type=="Contract" and s.status in ("Invoiced","No Charge") for s in schedules)
			done=contract_done and billed_upto and billed_upto>=max(getdate(doc.dismantle_date),end) and all(s.status!="Pending" for s in schedules)
			status="Completed" if done else "Dismantled"
		else: status="In Excess" if today>end else "Within Contract"
	doc.db_set({"actual_days":actual,"excess_days":excess,"billed_upto":billed_upto,"total_billed_amount":billed_amount,"status":status},update_modified=False)
	doc.notify_update()


def run_daily_jcr_billing():
	if not cint(get_settings().auto_generate_jcr_billing): return
	for name in frappe.get_all("Job Completion Report", filters={"docstatus":1,"status":["not in",["Completed","Cancelled"]]}, pluck="name"):
		try:
			generate_jcr_billing(name); frappe.db.commit()
		except Exception:
			frappe.db.rollback(); frappe.log_error(title=f"JCR billing failed for {name}", message=frappe.get_traceback())
