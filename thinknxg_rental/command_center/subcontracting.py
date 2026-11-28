"""Command Center: Subcontracting section (dashboard, action centre, work order 360, subcontractor 360).

Every figure is a query over the subcontracting documents and ERPNext's own Purchase Invoices, Payment Entries and GL;
nothing is stored twice. Every method checks Command Center staff access and the DocType permission of what it reads;
every action calls the documents' own role-checked workflow methods.
"""
import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, getdate, nowdate

from thinknxg_rental.command_center import registry as R
from thinknxg_rental.services import subcontracting as sc

SWO = "Subcontract Work Order"
DOC = "thinknxg_rental.subcontracting.doctype."


def _check(doctype=SWO):
	R.check_staff()
	if not frappe.has_permission(doctype, "read"):
		raise frappe.PermissionError(_("You do not have access to {0}").format(_(doctype)))


def _desk(doctype, name):
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}/{name}"


def _count(doctype, filters):
	return frappe.db.count(doctype, filters) if frappe.has_permission(doctype, "read") else None


def _money_rows():
	"""Per work order: contract, certified, invoiced, paid, retention, advance recovered."""
	return frappe.db.sql("""
		select w.name, w.supplier, w.supplier_name, w.project, w.status, w.contract_amount, w.final_contract_value,
			(select sum(wi.accepted_qty * wi.rate) from `tabSubcontract Work Item` wi where wi.parent = w.name) as certified,
			(select sum(wi.reported_qty * wi.rate) from `tabSubcontract Work Item` wi where wi.parent = w.name) as completed,
			(select sum(s.certified_value) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as invoiced,
			(select sum(s.retention_amount) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as retention,
			(select sum(s.advance_recovery) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as advance_recovered,
			(select sum(pi.grand_total - pi.outstanding_amount) from `tabPurchase Invoice` pi where pi.subcontract_work_order = w.name and pi.docstatus = 1) as paid,
			(select sum(pi.outstanding_amount) from `tabPurchase Invoice` pi where pi.subcontract_work_order = w.name and pi.docstatus = 1) as outstanding
		from `tabSubcontract Work Order` w where w.docstatus = 1 and w.status != 'Cancelled'""", as_dict=True)


# ----------------------------------------------------------------------------------------------------- dashboard
@frappe.whitelist()
def dashboard():
	_check()
	today = getdate(nowdate())
	s = sc.settings()
	alert = cint(s.compliance_alert_days or 30)
	working = list(sc.WORKING)
	money = _money_rows()
	tot = lambda k: sum(flt(r.get(k)) for r in money)  # noqa: E731
	delayed = frappe.get_all(SWO, filters=[["docstatus", "=", 1], ["status", "in", working], ["expected_completion_date", "is", "set"],
		["expected_completion_date", "<", today]],
		fields=["name", "supplier_name", "project", "expected_completion_date", "status"], order_by="expected_completion_date")
	kpis = [
		("subcontractors", _("Active subcontractors"), frappe.db.count("Supplier", {"is_subcontractor": 1, "disabled": 0, "subcontractor_approval_status": "Approved"}),
			"subcontracting/subcontractors"),
		("pending_subs", _("Subcontractors awaiting approval"), frappe.db.count("Supplier", {"is_subcontractor": 1, "disabled": 0, "subcontractor_approval_status": "Pending"}),
			"subcontracting/subcontractors?approval=Pending"),
		("agreements", _("Active agreements"), _count("Subcontract Agreement", {"docstatus": 1, "status": "Active"}), "subcontracting/agreements"),
		("work_orders", _("Work orders"), frappe.db.count(SWO, {"docstatus": 1, "status": ["!=", "Cancelled"]}), "subcontracting/work-orders"),
		("in_progress", _("Work orders in progress"), frappe.db.count(SWO, {"docstatus": 1, "status": ["in", ["Work In Progress", "Partially Completed"]]}),
			"subcontracting/work-orders?status=progress"),
		("delayed", _("Delayed work orders"), len(delayed), "subcontracting/work-orders?status=delayed", "bad"),
		("inspections", _("Inspections pending"), _count("Subcontract Work Progress", {"docstatus": 0, "inspection_status": ["in", ["Inspection Requested", "Under Inspection"]]}),
			"subcontracting/inspections"),
		("progress", _("Progress reports to review"), _count("Subcontract Daily Progress", {"docstatus": 0, "status": "Submitted"}), "subcontracting/daily-progress"),
		("materials", _("Open material requests"), _count("Subcontract Material Request", {"status": ["in", ["Submitted", "Approved", "Partially Issued"]]}),
			"subcontracting/material-requests"),
		("invoices", _("Supplier invoices to verify"), _count("Subcontractor Invoice Submission", {"docstatus": 0, "status": "Submitted"}), "subcontracting/supplier-invoices"),
		("value", _("Total subcontract value"), tot("final_contract_value"), "subcontracting/work-orders", None, True),
		("certified", _("Certified work value"), tot("certified"), "subcontracting/work-orders", None, True),
		("outstanding", _("Outstanding payments"), tot("outstanding"), "subcontracting/settlements", None, True),
		("retention", _("Retention held"), tot("retention"), "reports/subcontract-retention", None, True),
	]
	kpis = [dict(key=k[0], label=k[1], value=k[2] or 0, route=k[3], tone=k[4] if len(k) > 4 else None, money=k[5] if len(k) > 5 else False)
		for k in kpis if k[2] is not None]

	by_status = frappe.db.sql("""select status, count(*) as n, sum(final_contract_value) as value from `tabSubcontract Work Order`
		where docstatus = 1 group by status order by n desc""", as_dict=True)
	by_project = frappe.db.sql("""select ifnull(project, %s) as label, count(*) as n, sum(final_contract_value) as value from `tabSubcontract Work Order`
		where docstatus = 1 and status != 'Cancelled' group by ifnull(project, %s) order by value desc limit 8""", (_("No project"), _("No project")), as_dict=True)
	by_sub = frappe.db.sql("""select supplier as `key`, supplier_name as label, count(*) as n, sum(final_contract_value) as value from `tabSubcontract Work Order`
		where docstatus = 1 and status != 'Cancelled' group by supplier, supplier_name order by value desc limit 8""", as_dict=True)
	start = get_first_day(add_months(today, -11))
	monthly = {r.m: r for r in frappe.db.sql("""select date_format(contract_date, '%%Y-%%m') as m, count(*) as n, sum(final_contract_value) as value
		from `tabSubcontract Work Order` where docstatus = 1 and contract_date >= %s group by m""", start, as_dict=True)}
	months = [add_months(start, i) for i in range(12)]
	planned = frappe.db.sql("""select date_format(expected_completion_date, '%%Y-%%m') as m, count(*) as n from `tabSubcontract Work Order`
		where docstatus = 1 and expected_completion_date >= %s group by m""", start, as_dict=True)
	actual = frappe.db.sql("""select date_format(actual_completion_date, '%%Y-%%m') as m, count(*) as n from `tabSubcontract Work Order`
		where docstatus = 1 and actual_completion_date >= %s group by m""", start, as_dict=True)
	pmap, amap = {r.m: r.n for r in planned}, {r.m: r.n for r in actual}
	progress = frappe.db.sql("""select ifnull(w.project, %s) as label, sum(wi.qty * wi.rate) as ordered, sum(wi.accepted_qty * wi.rate) as accepted,
		sum(wi.reported_qty * wi.rate) as reported from `tabSubcontract Work Item` wi join `tabSubcontract Work Order` w on w.name = wi.parent
		where w.docstatus = 1 and w.status in %s group by ifnull(w.project, %s) order by ordered desc limit 8""",
		(_("No project"), tuple(working + ["Completed"]), _("No project")), as_dict=True)
	charts = {
		"status": by_status, "project": by_project, "subcontractor": by_sub,
		"monthly": [{"label": m.strftime("%b %y"), "n": (monthly.get(m.strftime("%Y-%m")) or {}).get("n", 0),
			"value": flt((monthly.get(m.strftime("%Y-%m")) or {}).get("value"))} for m in months],
		"completion": [{"label": m.strftime("%b %y"), "planned": pmap.get(m.strftime("%Y-%m"), 0), "actual": amap.get(m.strftime("%Y-%m"), 0)} for m in months],
		"finance": {"contract": tot("final_contract_value"), "certified": tot("certified"), "invoiced": tot("invoiced"), "paid": tot("paid"),
			"outstanding": tot("outstanding"), "retention": tot("retention"), "advance_recovered": tot("advance_recovered"),
			"advance_paid": flt(frappe.db.sql("""select sum(paid_amount) from `tabPayment Entry` where docstatus = 1 and ifnull(subcontract_work_order, '') != ''
				and payment_type = 'Pay'""")[0][0])},
		"progress": progress,
	}
	return {"kpis": kpis, "charts": charts, "actions": actions(today, alert), "delayed": delayed[:10],
		"rejected": frappe.db.sql("""select p.name, p.subcontract_work_order, p.supplier, p.inspection_status, p.progress_date from `tabSubcontract Work Progress` p
			where p.docstatus = 1 and p.inspection_status in ('Rejected', 'Rework Required') order by p.progress_date desc limit 8""", as_dict=True),
		"settings_url": "/app/subcontracting-settings"}


def actions(today, alert):
	"""Everything that waits on staff, each with the actions that settle it."""
	out = []

	def add(group, doctype, rows, label, acts, sub=None):
		if not frappe.has_permission(doctype, "read"):
			return
		for r in rows:
			out.append({"group": group, "doctype": doctype, "name": r.name, "title": label(r), "sub": sub(r) if sub else None,
				"desk": _desk(doctype, r.name), "actions": acts, "route": f"subcontracting/work-orders/{r.subcontract_work_order}"
				if r.get("subcontract_work_order") else (f"subcontracting/work-orders/{r.name}" if doctype == SWO else None)})

	add(_("Pending approvals"), SWO, frappe.get_all(SWO, filters={"docstatus": 0, "status": "Pending Approval"}, fields=["name", "supplier_name", "final_contract_value"]),
		lambda r: _("Work order {0} for {1}").format(r.name, r.supplier_name), ["approve", "reject"])
	add(_("Pending approvals"), "Subcontract Agreement", frappe.get_all("Subcontract Agreement", filters={"docstatus": 0, "status": "Pending Approval"},
		fields=["name", "supplier_name", "agreement_type"]), lambda r: _("Agreement {0} ({1}) for {2}").format(r.name, r.agreement_type, r.supplier_name), ["approve", "reject"])
	subs = frappe.get_all("Supplier", filters={"is_subcontractor": 1, "disabled": 0, "subcontractor_approval_status": "Pending"}, fields=["name", "supplier_name"])
	for r in subs:
		out.append({"group": _("Pending approvals"), "doctype": "Supplier", "name": r.name, "title": _("New subcontractor {0}").format(r.supplier_name),
			"desk": _desk("Supplier", r.name), "actions": ["approve"], "route": f"subcontracting/subcontractors/{r.name}"})
	add(_("Ready to send"), SWO, frappe.get_all(SWO, filters={"docstatus": 1, "status": ["in", ["Approved", "Rejected by Subcontractor"]]},
		fields=["name", "supplier_name", "status", "subcontractor_response"]), lambda r: _("{0} for {1}").format(r.name, r.supplier_name), ["send"],
		lambda r: (_("Rejected: {0}").format(r.subcontractor_response) if r.status == "Rejected by Subcontractor" else _("Approved, not yet sent")))
	add(_("Awaiting subcontractor acceptance"), SWO, frappe.get_all(SWO, filters={"docstatus": 1, "status": "Sent to Subcontractor"},
		fields=["name", "supplier_name", "sent_on"]), lambda r: _("{0}, {1}").format(r.name, r.supplier_name), [], lambda r: _("Sent {0}").format(frappe.format(r.sent_on, "Datetime")))
	add(_("Progress updates to review"), "Subcontract Daily Progress", frappe.get_all("Subcontract Daily Progress", filters={"docstatus": 0, "status": "Submitted"},
		fields=["name", "subcontract_work_order", "supplier_name", "report_date"]), lambda r: _("{0}: {1} on {2}").format(r.name, r.supplier_name, frappe.format(r.report_date, "Date")),
		["approve", "return"])
	add(_("Inspection requests"), "Subcontract Work Progress", frappe.get_all("Subcontract Work Progress", filters={"docstatus": 0,
		"inspection_status": ["in", ["Inspection Requested", "Under Inspection"]]}, fields=["name", "subcontract_work_order", "supplier", "inspection_status", "proposed_inspection_date"]),
		lambda r: _("{0} on {1}").format(r.name, r.subcontract_work_order), ["start_inspection"],
		lambda r: "{0}{1}".format(_(r.inspection_status), (" · " + frappe.format(r.proposed_inspection_date, "Date")) if r.proposed_inspection_date else ""))
	add(_("Material requests"), "Subcontract Material Request", frappe.get_all("Subcontract Material Request", filters={"docstatus": 0, "status": "Submitted"},
		fields=["name", "subcontract_work_order", "supplier_name", "required_by"]), lambda r: _("{0} from {1}").format(r.name, r.supplier_name), ["approve", "reject"],
		lambda r: _("Needed by {0}").format(frappe.format(r.required_by, "Date")))
	add(_("Material to issue"), "Subcontract Material Request", frappe.get_all("Subcontract Material Request", filters={"docstatus": 1, "status": ["in", ["Approved", "Partially Issued"]]},
		fields=["name", "subcontract_work_order", "supplier_name", "required_by"]), lambda r: _("{0} for {1}").format(r.name, r.supplier_name), ["issue"])
	add(_("Invoice approvals"), "Subcontractor Invoice Submission", frappe.get_all("Subcontractor Invoice Submission", filters={"docstatus": 0, "status": "Submitted"},
		fields=["name", "subcontract_work_order", "supplier_name", "supplier_invoice_no", "total_claimed"]),
		lambda r: _("Invoice {0} from {1}").format(r.supplier_invoice_no, r.supplier_name), ["verify", "reject"], lambda r: frappe.format(r.total_claimed, "Currency"))
	add(_("Variation requests"), "Subcontract Variation", frappe.get_all("Subcontract Variation", filters={"docstatus": 0, "status": ["in", ["Submitted", "Under Review"]]},
		fields=["name", "subcontract_work_order", "supplier_name", "variation_type", "claimed_amount", "value_change"]),
		lambda r: _("{0}: {1} from {2}").format(r.name, _(r.variation_type), r.supplier_name), ["approve", "reject"],
		lambda r: frappe.format(r.value_change or r.claimed_amount, "Currency") if (r.value_change or r.claimed_amount) else None)
	add(_("Expiring agreements"), "Subcontract Agreement", frappe.get_all("Subcontract Agreement", filters={"docstatus": 1, "status": "Active",
		"end_date": ["<=", add_days(today, cint(sc.settings().agreement_alert_days or 30))]}, fields=["name", "supplier_name", "end_date"]),
		lambda r: _("{0} with {1}").format(r.name, r.supplier_name), [], lambda r: _("Ends {0}").format(frappe.format(r.end_date, "Date")))
	add(_("Overdue work orders"), SWO, frappe.get_all(SWO, filters=[["docstatus", "=", 1], ["status", "in", list(sc.WORKING)],
		["expected_completion_date", "is", "set"], ["expected_completion_date", "<", today]],
		fields=["name", "supplier_name", "expected_completion_date"]), lambda r: _("{0}, {1}").format(r.name, r.supplier_name), ["hold"],
		lambda r: _("Due {0}").format(frappe.format(r.expected_completion_date, "Date")))
	for r in frappe.get_all("Subcontractor Compliance Document", filters={"parenttype": "Supplier", "expiry_date": ["<=", add_days(today, alert)]},
			fields=["parent", "document_type", "expiry_date"], order_by="expiry_date"):
		out.append({"group": _("Compliance expiries"), "doctype": "Supplier", "name": r.parent, "title": _("{0}: {1}").format(r.parent, _(r.document_type)),
			"sub": _("Expires {0}").format(frappe.format(r.expiry_date, "Date")), "desk": _desk("Supplier", r.parent), "actions": [],
			"route": f"subcontracting/subcontractors/{r.parent}"})
	return out


ACTIONS = {
	(SWO, "approve"): DOC + "subcontract_work_order.subcontract_work_order.approve",
	(SWO, "reject"): DOC + "subcontract_work_order.subcontract_work_order.reject",
	(SWO, "send"): DOC + "subcontract_work_order.subcontract_work_order.send_to_subcontractor",
	(SWO, "hold"): DOC + "subcontract_work_order.subcontract_work_order.put_on_hold",
	(SWO, "resume"): DOC + "subcontract_work_order.subcontract_work_order.resume",
	(SWO, "start"): DOC + "subcontract_work_order.subcontract_work_order.start_work",
	("Subcontract Agreement", "approve"): DOC + "subcontract_agreement.subcontract_agreement.approve",
	("Subcontract Agreement", "reject"): DOC + "subcontract_agreement.subcontract_agreement.reject",
	("Supplier", "approve"): "thinknxg_rental.services.subcontracting.approve_subcontractor",
	("Subcontract Daily Progress", "approve"): DOC + "subcontract_daily_progress.subcontract_daily_progress.approve",
	("Subcontract Daily Progress", "return"): DOC + "subcontract_daily_progress.subcontract_daily_progress.return_for_correction",
	("Subcontract Work Progress", "start_inspection"): DOC + "subcontract_work_progress.subcontract_work_progress.start_inspection",
	("Subcontract Material Request", "approve"): DOC + "subcontract_material_request.subcontract_material_request.approve",
	("Subcontract Material Request", "reject"): DOC + "subcontract_material_request.subcontract_material_request.reject",
	("Subcontractor Invoice Submission", "verify"): DOC + "subcontractor_invoice_submission.subcontractor_invoice_submission.verify",
	("Subcontractor Invoice Submission", "reject"): DOC + "subcontractor_invoice_submission.subcontractor_invoice_submission.reject",
	("Subcontract Variation", "approve"): DOC + "subcontract_variation.subcontract_variation.approve",
	("Subcontract Variation", "reject"): DOC + "subcontract_variation.subcontract_variation.reject",
}
# the remark each action takes, and under which argument name
REMARK_ARG = {"reject": "reason", "return": "review_remarks", "hold": "reason"}
REMARK_ARG_BY_DT = {("Subcontract Material Request", "reject"): "review_remarks", ("Subcontract Daily Progress", "approve"): "review_remarks",
	("Subcontract Material Request", "approve"): "review_remarks", ("Subcontractor Invoice Submission", "verify"): "review_remarks",
	("Subcontract Variation", "approve"): "external_remarks"}


@frappe.whitelist(methods=["POST"])
def act(doctype, name, action, remarks=None, amount=None):
	"""Run one action from the action centre through the document's own workflow method (which checks the role)."""
	R.check_staff()
	method = ACTIONS.get((doctype, action))
	if not method:
		frappe.throw(_("Unknown action"))
	kwargs = {"supplier": name} if doctype == "Supplier" else {"name": name}
	arg = REMARK_ARG_BY_DT.get((doctype, action)) or REMARK_ARG.get(action)
	if arg and remarks is not None:
		kwargs[arg] = remarks
	if (doctype, action) == ("Subcontract Variation", "approve") and amount not in (None, ""):
		kwargs["approved_amount"] = flt(amount)
	if (doctype, action) == ("Supplier", "approve") and remarks:
		kwargs["remarks"] = remarks
	result = frappe.get_attr(method)(**kwargs)
	return {"result": result}


# ----------------------------------------------------------------------------------------------------- work orders
@frappe.whitelist()
def work_orders(status=None, search=None, project=None, supplier=None, site=None, manager=None, from_date=None, to_date=None, page=1):
	_check()
	today = getdate(nowdate())
	cond, v = ["w.docstatus < 2"], {"today": today}
	if status == "progress":
		cond.append("w.status in ('Work In Progress', 'Partially Completed')")
	elif status == "delayed":
		cond.append("w.status in %(working)s and w.expected_completion_date < %(today)s")
		v["working"] = sc.WORKING
	elif status == "on-schedule":
		cond.append("w.status in %(working)s and (w.expected_completion_date is null or w.expected_completion_date >= %(today)s)")
		v["working"] = sc.WORKING
	elif status == "approval":
		cond.append("w.status = 'Pending Approval'")
	elif status:
		cond.append("w.status = %(status)s")
		v["status"] = status
	for f, col, val in (("project", "w.project", project), ("supplier", "w.supplier", supplier), ("site", "w.rental_site", site)):
		if val:
			cond.append(f"{col} = %({f})s")
			v[f] = val
	if manager:
		cond.append("(w.project_manager = %(m)s or w.site_engineer = %(m)s or w.coordinator = %(m)s)")
		v["m"] = manager
	if from_date:
		cond.append("w.contract_date >= %(from_date)s")
		v["from_date"] = from_date
	if to_date:
		cond.append("w.contract_date <= %(to_date)s")
		v["to_date"] = to_date
	if search:
		cond.append("(w.name like %(s)s or w.supplier_name like %(s)s or w.work_description like %(s)s or w.project like %(s)s)")
		v["s"] = f"%{search}%"
	page = max(cint(page), 1)
	rows = frappe.db.sql(f"""select w.name, w.supplier, w.supplier_name, w.project, w.rental_site, w.work_description, w.final_contract_value, w.currency,
		w.contract_date, w.start_date, w.expected_completion_date, w.status, w.docstatus, w.subcontract_type,
		(select sum(wi.accepted_qty * wi.rate) from `tabSubcontract Work Item` wi where wi.parent = w.name) as completed_value,
		(select sum(wi.qty) from `tabSubcontract Work Item` wi where wi.parent = w.name) as ordered,
		(select sum(wi.accepted_qty) from `tabSubcontract Work Item` wi where wi.parent = w.name) as accepted
		from `tabSubcontract Work Order` w where {' and '.join(cond)} order by w.modified desc limit 51 offset {(page - 1) * 50}""", v, as_dict=True)
	for r in rows:
		r.progress = round(100 * flt(r.accepted) / flt(r.ordered), 1) if flt(r.ordered) else 0
		r.delayed = r.status in sc.WORKING and r.expected_completion_date and getdate(r.expected_completion_date) < today
		r.approval = "Approved" if r.docstatus == 1 else r.status
	return {"rows": rows[:50], "more": len(rows) > 50, "can_create": frappe.has_permission(SWO, "create")}


@frappe.whitelist()
def work_order(name):
	_check()
	d = frappe.get_doc(SWO, name)
	d.check_permission("read")
	wo = {"subcontract_work_order": name}
	sub = lambda dt, fields, f=None, order="creation desc": frappe.get_all(dt, filters=dict(wo, **(f or {})), fields=fields, order_by=order) if frappe.has_permission(dt, "read") else []  # noqa: E731
	items = [{k: r.get(k) for k in ("name", "job_type", "description", "work_category", "uom", "qty", "rate", "amount", "reported_qty", "accepted_qty",
		"rejected_qty", "invoiced_qty", "is_additional", "variation", "hoc_item")} for r in d.items]
	m = next((r for r in _money_rows() if r.name == name), frappe._dict())
	variations = sub("Subcontract Variation", ["name", "variation_type", "status", "value_change", "claimed_amount", "approved_amount", "request_date", "source"])
	pending_var = sum(flt(v.value_change or v.claimed_amount) for v in variations if v.status in ("Submitted", "Under Review"))
	approved_var = sum(flt(v.value_change) for v in variations if v.status == "Approved")
	cost = {"original": flt(d.contract_amount), "approved_variations": approved_var, "revised": flt(d.final_contract_value),
		"completed": flt(m.completed), "certified": flt(m.certified), "invoiced": flt(m.invoiced), "paid": flt(m.paid), "retention": flt(m.retention),
		"advance_paid": sc.advance_paid(name)[0], "advance_recovered": flt(m.advance_recovered), "outstanding": flt(m.outstanding),
		"forecast": flt(d.final_contract_value) + pending_var}
	cost["utilization"] = round(100 * cost["certified"] / cost["revised"], 1) if cost["revised"] else 0
	pis = frappe.get_all("Purchase Invoice", filters={"subcontract_work_order": name, "docstatus": ["<", 2]},
		fields=["name", "bill_no", "posting_date", "grand_total", "outstanding_amount", "status", "docstatus"], order_by="posting_date desc") if frappe.has_permission("Purchase Invoice", "read") else []
	pes = frappe.get_all("Payment Entry", filters={"subcontract_work_order": name, "docstatus": 1},
		fields=["name", "posting_date", "paid_amount", "reference_no", "mode_of_payment", "unallocated_amount"], order_by="posting_date desc") if frappe.has_permission("Payment Entry", "read") else []
	pes += frappe.db.sql("""select distinct pe.name, pe.posting_date, pe.paid_amount, pe.reference_no, pe.mode_of_payment, pe.unallocated_amount
		from `tabPayment Entry` pe join `tabPayment Entry Reference` r on r.parent = pe.name where pe.docstatus = 1 and r.reference_doctype = 'Purchase Invoice'
		and r.reference_name in %s and ifnull(pe.subcontract_work_order, '') = ''""", (tuple(p.name for p in pis) or ("",),), as_dict=True) if pis else []
	docs = {
		"progress": sub("Subcontract Daily Progress", ["name", "report_date", "status", "labour_deployed", "delay_reported", "source"]),
		"inspections": sub("Subcontract Work Progress", ["name", "progress_date", "inspection_status", "docstatus", "source", "proposed_inspection_date"]),
		"completion": sub("Subcontract Completion Report", ["name", "completion_date", "certified_value", "docstatus"]),
		"material_requests": sub("Subcontract Material Request", ["name", "request_date", "required_by", "status", "source"]),
		"issues": sub("Subcontract Material Allocation", ["name", "posting_date", "docstatus", "stock_entry", "received_by_subcontractor", "shortage_reported"]),
		"returns": sub("Subcontract Material Return", ["name", "posting_date", "docstatus", "total_recovery"]),
		"variations": variations,
		"submissions": sub("Subcontractor Invoice Submission", ["name", "supplier_invoice_no", "supplier_invoice_date", "status", "total_claimed", "purchase_invoice"]),
		"settlements": sub("Subcontract Settlement", ["name", "posting_date", "settlement_type", "certified_value", "final_payable", "purchase_invoice", "docstatus"]),
		"purchase_invoices": pis, "payments": pes,
	}
	materials = [{"item_code": k, **v} for k, v in sc.issued_balance(name).items()]
	timeline = []
	for key, dt, date_f in (("progress", "Subcontract Daily Progress", "report_date"), ("inspections", "Subcontract Work Progress", "progress_date"),
			("completion", "Subcontract Completion Report", "completion_date"), ("material_requests", "Subcontract Material Request", "request_date"),
			("issues", "Subcontract Material Allocation", "posting_date"), ("returns", "Subcontract Material Return", "posting_date"),
			("variations", "Subcontract Variation", "request_date"), ("submissions", "Subcontractor Invoice Submission", "supplier_invoice_date"),
			("settlements", "Subcontract Settlement", "posting_date"), ("purchase_invoices", "Purchase Invoice", "posting_date"), ("payments", "Payment Entry", "posting_date")):
		for r in docs[key]:
			timeline.append({"date": r.get(date_f), "doctype": dt, "name": r.name, "status": r.get("status") or r.get("inspection_status")
				or {0: _("Draft"), 1: _("Submitted"), 2: _("Cancelled")}.get(r.get("docstatus")), "desk": _desk(dt, r.name)})
	if d.purchase_order:
		timeline.append({"date": frappe.db.get_value("Purchase Order", d.purchase_order, "transaction_date"), "doctype": "Purchase Order", "name": d.purchase_order,
			"desk": _desk("Purchase Order", d.purchase_order)})
	timeline.sort(key=lambda r: str(r["date"] or ""), reverse=True)
	comments = frappe.get_all("Comment", filters={"reference_doctype": SWO, "reference_name": name, "comment_type": ["in", ["Comment", "Info"]]},
		fields=["content", "owner", "creation", "comment_type"], order_by="creation desc", limit=40)
	head = d.as_dict(no_default_fields=True)
	head.pop("items", None)
	head.update(name=d.name, docstatus=d.docstatus)
	can = lambda role_list: bool(set(role_list) & set(frappe.get_roles()))  # noqa: E731
	mgr = can([sc.MANAGER, "System Manager"])
	actions = []
	if d.docstatus == 0 and d.status == "Draft" and can([sc.MANAGER, sc.EXECUTIVE, "System Manager"]):
		actions.append("submit_for_approval")
	if d.docstatus == 0 and d.status == "Pending Approval" and mgr:
		actions += ["approve", "reject"]
	if d.docstatus == 1 and d.status in ("Approved", "Rejected by Subcontractor") and can([sc.MANAGER, sc.EXECUTIVE, "System Manager"]):
		actions.append("send")
	if d.docstatus == 1 and d.status in ("Approved", "Sent to Subcontractor", "Accepted by Subcontractor") and can([sc.MANAGER, sc.SITE_ENGINEER, "System Manager"]):
		actions.append("start")
	if d.docstatus == 1 and d.status not in ("On Hold", "Pending Final Verification", "Verified", "Closed", "Cancelled") and mgr:
		actions.append("hold")
	if d.docstatus == 1 and d.status == "On Hold" and mgr:
		actions.append("resume")
	return {"doc": head, "items": items, "cost": cost, "docs": docs, "materials": materials, "timeline": timeline, "comments": comments,
		"messages": frappe.get_all("Subcontract Message", filters={"subcontract_work_order": name}, fields=["name", "direction", "subject", "message",
			"sender_name", "creation", "read_by_staff"], order_by="creation desc", limit=50),
		"actions": actions, "desk": _desk(SWO, name), "new": {dt: f"/app/{frappe.scrub(dt).replace('_', '-')}/new?subcontract_work_order={name}"
			for dt in ("Subcontract Daily Progress", "Subcontract Work Progress", "Subcontract Material Request", "Subcontract Material Allocation",
				"Subcontract Material Return", "Subcontract Variation", "Subcontractor Invoice Submission", "Subcontract Completion Report")}}


@frappe.whitelist(methods=["POST"])
def wo_action(name, action, remarks=None):
	R.check_staff()
	method = {"submit_for_approval": DOC + "subcontract_work_order.subcontract_work_order.submit_for_approval"}.get(action) or ACTIONS.get((SWO, action))
	if not method:
		frappe.throw(_("Unknown action"))
	kwargs = {"name": name}
	if action in REMARK_ARG and remarks is not None:
		kwargs[REMARK_ARG[action]] = remarks
	return {"result": frappe.get_attr(method)(**kwargs)}


@frappe.whitelist(methods=["POST"])
def send_message(supplier, message, work_order=None, subject=None, announcement=0):
	R.check_staff()
	if not frappe.has_permission("Subcontract Message", "create"):
		raise frappe.PermissionError(_("You cannot write to subcontractors"))
	doc = frappe.get_doc({"doctype": "Subcontract Message", "supplier": supplier, "subcontract_work_order": work_order or None, "subject": subject,
		"message": message, "direction": "Announcement" if cint(announcement) else "To Subcontractor", "read_by_staff": 1})
	doc.insert()
	if work_order:
		for n in frappe.get_all("Subcontract Message", filters={"subcontract_work_order": work_order, "direction": "From Subcontractor", "read_by_staff": 0}, pluck="name"):
			frappe.db.set_value("Subcontract Message", n, "read_by_staff", 1, update_modified=False)
	return doc.name


# ----------------------------------------------------------------------------------------------------- subcontractors
@frappe.whitelist()
def subcontractors(search=None, approval=None, classification=None):
	_check("Supplier")
	filters = {"is_subcontractor": 1}
	if approval:
		filters["subcontractor_approval_status"] = approval
	if classification:
		filters["business_classification"] = classification
	or_filters = {"supplier_name": ["like", f"%{search}%"], "name": ["like", f"%{search}%"]} if search else None
	rows = frappe.get_all("Supplier", filters=filters, or_filters=or_filters, fields=["name", "supplier_name", "subcontractor_approval_status",
		"business_classification", "subcontractor_type", "disabled", "service_areas"], order_by="supplier_name", limit=200)
	today = getdate(nowdate())
	for r in rows:
		w = frappe.db.sql("""select count(*), sum(status in %s), sum(status in %s and expected_completion_date < %s), sum(final_contract_value)
			from `tabSubcontract Work Order` where supplier = %s and docstatus = 1""", (sc.WORKING, sc.WORKING, today, r.name))[0]
		r.update(work_orders=cint(w[0]), ongoing=cint(w[1]), delayed=cint(w[2]), value=flt(w[3]))
		docs = frappe.get_all("Subcontractor Compliance Document", filters={"parent": r.name, "parenttype": "Supplier"}, fields=["expiry_date"])
		r.compliance = "Expired" if any(sc.compliance_status(x.expiry_date, 0) == "Expired" for x in docs) else (
			"Expiring" if any(sc.compliance_status(x.expiry_date) == "Expiring" for x in docs) else ("Valid" if docs else "None"))
		r.score = sc.scorecard(r.name)["score"]
	return {"rows": rows}


@frappe.whitelist()
def subcontractor(name, from_date=None, to_date=None):
	_check("Supplier")
	s = frappe.get_doc("Supplier", name)
	s.check_permission("read")
	if not s.get("is_subcontractor"):
		frappe.throw(_("{0} is not a subcontractor").format(name))
	company = frappe.db.get_single_value("Rental Settings", "company") or frappe.defaults.get_global_default("company")
	from_date = getdate(from_date) if from_date else add_months(getdate(nowdate()), -12)
	to_date = getdate(to_date) if to_date else getdate(nowdate())
	opening = flt(frappe.db.sql("""select sum(credit - debit) from `tabGL Entry` where party_type = 'Supplier' and party = %s and company = %s
		and is_cancelled = 0 and posting_date < %s""", (name, company, from_date))[0][0])
	entries = frappe.db.sql("""select posting_date, voucher_type, voucher_no, sum(debit) as debit, sum(credit) as credit, max(remarks) as remarks
		from `tabGL Entry` where party_type = 'Supplier' and party = %s and company = %s and is_cancelled = 0 and posting_date between %s and %s
		group by posting_date, voucher_type, voucher_no order by posting_date, min(creation)""", (name, company, from_date, to_date), as_dict=True) \
		if frappe.has_permission("GL Entry", "read") else []
	bal = opening
	for e in entries:
		bal += flt(e.credit) - flt(e.debit)
		e.balance = bal
		e.desk = _desk(e.voucher_type, e.voucher_no)
	wos = frappe.get_all(SWO, filters={"supplier": name, "docstatus": ["<", 2]}, fields=["name", "project", "status", "final_contract_value",
		"expected_completion_date", "work_description"], order_by="modified desc")
	return {
		"supplier": {k: s.get(k) for k in ("name", "supplier_name", "supplier_group", "tax_id", "email_id", "mobile_no", "website", "is_subcontractor",
			"subcontractor_type", "subcontractor_category", "approved_work_categories", "subcontractor_approval_status", "default_retention_percentage",
			"business_classification", "specializations", "relationship_manager", "subcontractor_contact_person", "operating_locations", "service_areas",
			"disabled", "default_currency")},
		"compliance": [dict(r.as_dict(), compliance_status=sc.compliance_status(r.expiry_date)) for r in s.get("compliance_documents") or []],
		"agreements": frappe.get_all("Subcontract Agreement", filters={"supplier": name}, fields=["name", "agreement_type", "status", "start_date", "end_date",
			"contract_value"], order_by="start_date desc"),
		"work_orders": wos,
		"projects": sorted({w.project for w in wos if w.project and w.status in sc.WORKING}),
		"inspections": frappe.db.sql("""select p.inspection_status as status, count(*) as n from `tabSubcontract Work Progress` p where p.supplier = %s
			and p.docstatus = 1 group by p.inspection_status""", name, as_dict=True),
		"material": frappe.get_all("Subcontract Material Allocation", filters={"supplier": name, "docstatus": 1}, fields=["name", "posting_date",
			"subcontract_work_order"], order_by="posting_date desc", limit=20),
		"variations": frappe.get_all("Subcontract Variation", filters={"supplier": name}, fields=["name", "variation_type", "status", "value_change",
			"subcontract_work_order"], order_by="creation desc", limit=20),
		"invoices": frappe.get_all("Purchase Invoice", filters={"supplier": name, "docstatus": 1}, fields=["name", "bill_no", "posting_date", "grand_total",
			"outstanding_amount", "status", "subcontract_work_order"], order_by="posting_date desc", limit=30) if frappe.has_permission("Purchase Invoice", "read") else [],
		"portal_users": frappe.get_all("Subcontractor Portal Access", filters={"supplier": name}, fields=["name", "full_name", "email", "access_level",
			"enabled", "last_access", "invited_on"]),
		"scorecard": sc.scorecard(name),
		"statement": {"company": company, "from_date": from_date, "to_date": to_date, "opening": opening, "entries": entries, "closing": bal},
		"messages": frappe.get_all("Subcontract Message", filters={"supplier": name}, fields=["name", "direction", "subject", "message", "sender_name",
			"creation", "subcontract_work_order"], order_by="creation desc", limit=30),
		"desk": _desk("Supplier", name),
		"can_approve": bool({sc.MANAGER, "System Manager"} & set(frappe.get_roles())),
	}


@frappe.whitelist()
def compare(suppliers=None, classification=None):
	"""Side by side: approved rates (active agreements), history, quality, completion, compliance and score."""
	_check("Supplier")
	names = frappe.parse_json(suppliers) if suppliers else frappe.get_all("Supplier", filters={"is_subcontractor": 1, "disabled": 0,
		**({"business_classification": classification} if classification else {})}, pluck="name", limit=12)
	out = []
	for n in names[:12]:
		card = sc.scorecard(n)
		rates = frappe.db.sql("""select r.item_code, min(r.rate) as rate from `tabSubcontract Agreement Rate` r join `tabSubcontract Agreement` a on a.name = r.parent
			where a.supplier = %s and a.docstatus = 1 and a.status = 'Active' group by r.item_code""", n, as_dict=True)
		hist = frappe.db.sql("""select wi.job_type, sum(wi.amount) / nullif(sum(wi.qty), 0) as avg_rate, sum(wi.qty) as qty from `tabSubcontract Work Item` wi
			join `tabSubcontract Work Order` w on w.name = wi.parent where w.supplier = %s and w.docstatus = 1 group by wi.job_type""", n, as_dict=True)
		projects = frappe.db.sql("select count(distinct project) from `tabSubcontract Work Order` where supplier = %s and docstatus = 1", n)[0][0]
		out.append({"supplier": n, "supplier_name": frappe.db.get_value("Supplier", n, "supplier_name"), "classification": frappe.db.get_value("Supplier", n, "business_classification"),
			"score": card["score"], "indicators": {i["key"]: i["score"] for i in card["indicators"]}, "work_orders": card["work_orders"], "projects": cint(projects),
			"available": card["work_orders"]["ongoing"] == 0, "rates": rates, "history": hist})
	return {"rows": out}
