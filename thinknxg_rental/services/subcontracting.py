"""Subcontracting of Hire Order Contracts: allocation, status and cost rules shared by the Subcontracting documents.

Allocation rule (the heart of the module). For every job line of a Hire Order Contract

    available = contract quantity of the line - quantity on SUBMITTED Subcontract Work Orders

A Draft or Pending Approval work order does not use up quantity; a cancelled one gives it back. The check runs
on the server while the Hire Order Contract row is locked, so two work orders submitted at the same time cannot
allocate the same remaining quantity.
"""
import frappe
from frappe import _
from frappe.utils import getdate, cint, nowdate, flt

EPS = 1e-9
MANAGER = "Subcontracting Manager"
EXECUTIVE = "Subcontracting Executive"
SITE_ENGINEER = "Site Engineer"
STORE_MANAGER = "Store Manager"
ACCOUNTS = ("Accounts Manager", "Accounts User")
ROLES = (MANAGER, EXECUTIVE, SITE_ENGINEER, STORE_MANAGER, "Project Manager")


def require_role(*roles):
	"""Server-side gate for every approval step: the client can never skip it. System Manager and Administrator pass."""
	have = set(frappe.get_roles())
	if frappe.session.user == "Administrator" or "System Manager" in have or have & set(roles):
		return
	frappe.throw(_("Only {0} can do this").format(_(" or ").join(roles)), frappe.PermissionError)


def lock_contract(hire_order_contract):
	"""Serialise allocation on one Hire Order Contract: the second request waits, then sees the first."""
	frappe.db.sql("select name from `tabHire Order Contract` where name = %s for update", hire_order_contract)


def job_lines(hire_order_contract):
	return {r.name: r for r in frappe.get_all("Hire Order Contract Item", filters={"parent": hire_order_contract, "parenttype": "Hire Order Contract"},
		fields=["name", "job_type", "job_type_name", "qty", "contract_rate", "contract_amount", "location"], order_by="idx")}


def allocated_qty(hire_order_contract, hoc_item=None, exclude=None):
	"""Quantity on submitted work orders (not additional work), per job line unless a line is named."""
	cond, values = "", {"hoc": hire_order_contract}
	if hoc_item:
		cond += " and wi.hoc_item = %(item)s"
		values["item"] = hoc_item
	if exclude:
		cond += " and w.name != %(exclude)s"
		values["exclude"] = exclude
	rows = frappe.db.sql(
		f"""select wi.hoc_item, sum(wi.qty) as qty from `tabSubcontract Work Item` wi
		join `tabSubcontract Work Order` w on w.name = wi.parent
		where w.docstatus = 1 and w.hire_order_contract = %(hoc)s and ifnull(wi.is_additional, 0) = 0 and ifnull(wi.hoc_item, '') != '' {cond}
		group by wi.hoc_item""", values, as_dict=True)
	return {r.hoc_item: flt(r.qty) for r in rows}


def line_availability(hire_order_contract, exclude=None):
	"""One row per job line: contract quantity, approved subcontract quantity, balance."""
	used = allocated_qty(hire_order_contract, exclude=exclude)
	out = []
	for name, line in job_lines(hire_order_contract).items():
		approved = used.get(name, 0)
		out.append(frappe._dict(hoc_item=name, job_type=line.job_type, job_type_name=line.job_type_name, location=line.location,
			contract_qty=flt(line.qty), subcontracted_qty=approved, available_qty=max(flt(line.qty) - approved, 0)))
	return out


def refresh_status(swo):
	"""Work-in-progress status of an approved work order, from what has been reported and accepted."""
	doc = frappe.get_doc("Subcontract Work Order", swo) if isinstance(swo, str) else swo
	if doc.docstatus != 1 or doc.status in ("Pending Final Verification", "Verified", "Closed", "Cancelled", "On Hold"):
		return doc.status
	rows = doc.items
	if rows and all(flt(r.accepted_qty) >= flt(r.qty) - EPS for r in rows):
		status = "Completed"
	elif any(flt(r.accepted_qty) > EPS for r in rows):
		status = "Partially Completed"
	elif any(flt(r.completed_qty) > EPS for r in rows):
		status = "Work In Progress"
	elif doc.status in RELEASED + ("Rejected by Subcontractor",):
		status = doc.status  # nothing done yet: keep where the hand-over to the subcontractor stands
	else:
		status = "Approved"
	if status == "Completed" and not doc.get("actual_completion_date"):
		doc.db_set("actual_completion_date", nowdate(), update_modified=False)
	if status in ("Work In Progress", "Partially Completed", "Completed") and not doc.get("actual_start_date"):
		doc.db_set("actual_start_date", nowdate(), update_modified=False)
	if status != doc.status:
		doc.db_set("status", status, update_modified=False)
		doc.status = status
	return status


def subcontract_summary(hire_order_contract):
	"""The Subcontracting block of a Hire Order Contract."""
	lines = line_availability(hire_order_contract)
	total = sum(r.contract_qty for r in lines)
	used = sum(r.subcontracted_qty for r in lines)
	orders = frappe.get_all("Subcontract Work Order", filters={"hire_order_contract": hire_order_contract, "docstatus": 1},
		fields=["name", "supplier", "status", "labour_cost", "equipment_cost", "final_contract_value", "currency"])
	items = frappe.db.sql(
		"""select sum(wi.qty) as qty, sum(wi.accepted_qty) as accepted from `tabSubcontract Work Item` wi
		join `tabSubcontract Work Order` w on w.name = wi.parent where w.docstatus = 1 and w.hire_order_contract = %s""",
		hire_order_contract, as_dict=True)[0]
	actual = 0 if not frappe.db.table_exists("Subcontract Settlement") else flt(frappe.db.sql("""select sum(s.certified_value) from `tabSubcontract Settlement` s join `tabSubcontract Work Order` w on w.name = s.subcontract_work_order
		where s.docstatus = 1 and w.hire_order_contract = %s""", hire_order_contract)[0][0])
	qty, accepted = flt(items.qty), flt(items.accepted)
	return {
		"lines": lines,
		"total_contract_qty": total,
		"subcontracted_qty": used,
		"balance_qty": max(total - used, 0),
		"subcontractors": len({o.supplier for o in orders}),
		"work_orders": len(orders),
		"draft_work_orders": frappe.db.count("Subcontract Work Order", {"hire_order_contract": hire_order_contract, "docstatus": 0}),
		"labour_cost": sum(flt(o.labour_cost) for o in orders),
		"equipment_cost": sum(flt(o.equipment_cost) for o in orders),
		"estimated_cost": sum(flt(o.final_contract_value) for o in orders),
		"actual_cost": actual,
		"completion_pct": round(accepted / qty * 100, 1) if qty else 0,
		"currency": frappe.db.get_value("Company", frappe.db.get_value("Hire Order Contract", hire_order_contract, "company"), "default_currency"),
	}


# ----- material custody --------------------------------------------------------------------------------------
CUSTODY = "Subcontractor Custody"


def custody_warehouse(company):
	"""One custody warehouse per company holds everything issued to subcontractors; the ledger says whose it is."""
	from thinknxg_rental.services.setup import ensure_warehouse

	return ensure_warehouse("Subcontractor Custody", company)


def issued_balance(subcontract_work_order, exclude_return=None):
	"""{item_code: {issued, installed, returned, damaged, missing, outstanding}} from submitted allocations and returns."""
	out = {}
	for r in frappe.db.sql(
		"""select i.item_code, sum(i.qty) as qty from `tabSubcontract Material Item` i join `tabSubcontract Material Allocation` a on a.name = i.parent
		where a.docstatus = 1 and a.subcontract_work_order = %s group by i.item_code""", subcontract_work_order, as_dict=True):
		out[r.item_code] = frappe._dict(issued=flt(r.qty), installed=0, returned=0, damaged=0, missing=0)
	cond = " and r.name != %s" if exclude_return else ""
	args = (subcontract_work_order, exclude_return) if exclude_return else (subcontract_work_order,)
	for r in frappe.db.sql(
		f"""select i.item_code, sum(i.installed_qty) as installed, sum(i.returned_qty) as returned, sum(i.damaged_qty) as damaged, sum(i.missing_qty) as missing
		from `tabSubcontract Return Item` i join `tabSubcontract Material Return` r on r.name = i.parent
		where r.docstatus = 1 and r.subcontract_work_order = %s {cond} group by i.item_code""", args, as_dict=True):
		row = out.setdefault(r.item_code, frappe._dict(issued=0, installed=0, returned=0, damaged=0, missing=0))
		row.update(installed=flt(r.installed), returned=flt(r.returned), damaged=flt(r.damaged), missing=flt(r.missing))
	for row in out.values():
		row.outstanding = row.issued - row.installed - row.returned - row.damaged - row.missing
	return out


# statuses in which work is released and being done (or about to be)
RELEASED = ("Approved", "Sent to Subcontractor", "Accepted by Subcontractor")
WORKING = RELEASED + ("Work In Progress", "Partially Completed")
BILLABLE = WORKING + ("Completed", "Pending Final Verification", "Verified")


def work_order_for_document(doc, statuses=WORKING + ("Completed",)):
	swo = frappe.db.get_value("Subcontract Work Order", doc.subcontract_work_order,
		["name", "docstatus", "status", "company", "supplier", "customer", "project", "rental_site", "hire_order_contract"], as_dict=True)
	if not swo or swo.docstatus != 1:
		frappe.throw(_("Subcontract Work Order {0} must be approved first").format(doc.subcontract_work_order))
	if statuses and swo.status not in statuses:
		frappe.throw(_("Subcontract Work Order {0} is {1}; this is allowed only while it is {2}").format(swo.name, swo.status, ", ".join(statuses)))
	return swo


def lock_work_order(name):
	frappe.db.sql("select name from `tabSubcontract Work Order` where name = %s for update", name)


def set_status(name, status):
	frappe.db.set_value("Subcontract Work Order", name, "status", status)


# ----- accounts and money ------------------------------------------------------------------------------------
def settlement_accounts(company):
	"""Retention held (liability) and cost recoveries (expense, credited). Created once per company, no hard-coded names in documents."""
	out = {}
	spec = (("retention_account", "Subcontractor Retention Payable", "Liability", ("Current Liabilities", "Current Liability")),
		("recovery_account", "Subcontract Cost Recoveries", "Expense", ("Direct Expenses", "Indirect Expenses", "Expenses")))
	for key, label, root, parents in spec:
		name = frappe.db.get_value("Account", {"company": company, "account_name": label, "is_group": 0}, "name")
		if not name:
			parent = (frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": root, "account_name": ["in", parents]}, "name")
				or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": root}, "name", order_by="lft desc"))
			if not parent:
				frappe.throw(_("Company {0} has no {1} account group").format(company, root))
			acc = frappe.get_doc({"doctype": "Account", "account_name": label, "company": company, "parent_account": parent, "root_type": root,
				"is_group": 0, "account_currency": frappe.get_cached_value("Company", company, "default_currency")})
			acc.flags.ignore_permissions = True
			acc.insert()
			name = acc.name
		out[key] = name
	return out


def advance_paid(swo, exclude_settlement=None):
	"""(paid, recovered): advances paid to the subcontractor against this work order, and how much earlier settlements took back."""
	paid = flt(frappe.db.sql("""select sum(paid_amount) from `tabPayment Entry` where docstatus = 1 and payment_type = 'Pay' and subcontract_work_order = %s
		and ifnull(is_advance_payment, 0) = 1""", swo)[0][0]) if frappe.get_meta("Payment Entry").has_field("is_advance_payment") else flt(frappe.db.sql(
		"""select sum(pe.paid_amount) from `tabPayment Entry` pe where pe.docstatus = 1 and pe.payment_type = 'Pay' and pe.subcontract_work_order = %s
		and not exists (select 1 from `tabPayment Entry Reference` r where r.parent = pe.name and r.reference_doctype = 'Purchase Invoice')""", swo)[0][0])
	cond, args = "", [swo]
	if exclude_settlement:
		cond, args = " and name != %s", [swo, exclude_settlement]
	rec = flt(frappe.db.sql(f"select sum(advance_recovery) from `tabSubcontract Settlement` where docstatus = 1 and subcontract_work_order = %s {cond}", args)[0][0])
	return paid, rec


def unsettled_recovery(swo, exclude_settlement=None):
	"""Damage and loss charged on returns that no settlement has taken yet."""
	charged = flt(frappe.db.sql("select sum(total_recovery) from `tabSubcontract Material Return` where docstatus = 1 and subcontract_work_order = %s", swo)[0][0])
	cond, args = "", [swo]
	if exclude_settlement:
		cond, args = " and name != %s", [swo, exclude_settlement]
	taken = flt(frappe.db.sql(f"select sum(damage_recovery) from `tabSubcontract Settlement` where docstatus = 1 and subcontract_work_order = %s {cond}", args)[0][0])
	return max(charged - taken, 0)


# ----- v2: settings, compliance, scorecard ----------------------------------------------------------------------
def settings():
	return frappe.get_cached_doc("Subcontracting Settings")


def compliance_status(expiry_date, alert_days=None):
	if not expiry_date:
		return "No Expiry"
	days = (getdate(expiry_date) - getdate(nowdate())).days
	if days < 0:
		return "Expired"
	if days <= (alert_days if alert_days is not None else cint(settings().compliance_alert_days or 30)):
		return "Expiring"
	return "Valid"


def supplier_validate(doc, method=None):
	"""Supplier hook: compliance document status, and approval status only through approve_subcontractor."""
	if not doc.get("is_subcontractor"):
		return
	alert = cint(settings().compliance_alert_days or 30)
	for r in doc.get("compliance_documents") or []:
		if r.expiry_date and r.issue_date and getdate(r.expiry_date) < getdate(r.issue_date):
			frappe.throw(_("Compliance row {0}: expiry date is before the issue date").format(r.idx))
		r.compliance_status = compliance_status(r.expiry_date, alert)
	if doc.is_new() or frappe.flags.in_install or frappe.flags.in_patch or frappe.flags.in_migrate or doc.flags.approving_subcontractor:
		return
	before = frappe.db.get_value("Supplier", doc.name, "subcontractor_approval_status")
	if before != doc.get("subcontractor_approval_status") and MANAGER not in frappe.get_roles() and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a Subcontracting Manager can change the approval status of a subcontractor"), frappe.PermissionError)


@frappe.whitelist()
def approve_subcontractor(supplier, status="Approved", remarks=None):
	require_role(MANAGER)
	if status not in ("Approved", "Suspended", "Blacklisted", "Pending"):
		frappe.throw(_("Unknown approval status {0}").format(status))
	doc = frappe.get_doc("Supplier", supplier)
	if not doc.get("is_subcontractor"):
		frappe.throw(_("{0} is not set up as a Subcontractor").format(supplier))
	if status == "Approved":
		expired = [r.document_type for r in doc.get("compliance_documents") or [] if compliance_status(r.expiry_date, 0) == "Expired"]
		if expired:
			frappe.throw(_("Renew the expired compliance documents first: {0}").format(", ".join(expired)))
	doc.subcontractor_approval_status = status
	doc.flags.approving_subcontractor = True
	doc.save()
	doc.add_comment("Info", _("Subcontractor {0} by {1}{2}").format(status, frappe.session.user, (": " + remarks) if remarks else ""))
	return status


def _pct(num, den, default=None):
	return round(100.0 * num / den, 1) if den else default


def scorecard(supplier):
	"""Transparent performance score: every indicator 0-100 with its inputs, and the weighted average."""
	s = settings()
	today = getdate(nowdate())
	wos = frappe.get_all("Subcontract Work Order", filters={"supplier": supplier, "docstatus": 1},
		fields=["name", "status", "expected_completion_date", "actual_completion_date", "sent_on", "responded_on"])
	done = [w for w in wos if w.status in ("Completed", "Pending Final Verification", "Verified", "Closed")]
	on_time = [w for w in done if w.expected_completion_date and getdate(w.actual_completion_date or today) <= getdate(w.expected_completion_date)]
	q = frappe.db.sql("""select sum(pi.accepted_qty), sum(pi.rejected_qty), sum(pi.rework_qty) from `tabSubcontract Progress Item` pi
		join `tabSubcontract Work Progress` p on p.name = pi.parent where p.docstatus = 1 and p.supplier = %s""", supplier)[0]
	acc, rej, rew = flt(q[0]), flt(q[1]), flt(q[2])
	docs = frappe.get_all("Subcontractor Compliance Document", filters={"parent": supplier, "parenttype": "Supplier"}, fields=["expiry_date"])
	valid = [d for d in docs if compliance_status(d.expiry_date, 0) != "Expired"]
	m = frappe.db.sql("""select sum(ri.returned_qty + ri.installed_qty), sum(ri.missing_qty + ri.damaged_qty) from `tabSubcontract Return Item` ri
		join `tabSubcontract Material Return` r on r.name = ri.parent where r.docstatus = 1 and r.supplier = %s""", supplier)[0]
	good, lost = flt(m[0]), flt(m[1])
	responded = [w for w in wos if w.sent_on and w.responded_on]
	avg_hours = (sum((w.responded_on - w.sent_on).total_seconds() for w in responded) / 3600 / len(responded)) if responded else None
	subs = frappe.get_all("Subcontractor Invoice Submission", filters={"supplier": supplier, "status": ["in", ["Verified", "Rejected"]]}, pluck="status")
	ind = [
		("on_time", _("On-time completion"), _pct(len(on_time), len(done)), _("{0} of {1} finished work orders on time").format(len(on_time), len(done))),
		("quality", _("Work quality"), _pct(acc, acc + rej), _("{0} accepted, {1} rejected").format(acc, rej)),
		("rework", _("Rework"), (100 - _pct(rew, acc + rej + rew)) if (acc + rej + rew) else None, _("{0} sent back for rework").format(rew)),
		("safety", _("Safety and compliance"), _pct(len(valid), len(docs)), _("{0} of {1} documents valid").format(len(valid), len(docs))),
		("material", _("Material management"), _pct(good, good + lost), _("{0} lost or damaged of {1} reconciled").format(lost, good + lost)),
		("response", _("Response time"), None if avg_hours is None else max(0, round(100 - avg_hours * 100 / 72, 1)),
			_("average {0} hours to accept or reject").format(round(avg_hours, 1)) if avg_hours is not None else _("no responses yet")),
		("commercial", _("Commercial compliance"), _pct(subs.count("Verified"), len(subs)), _("{0} of {1} invoices verified").format(subs.count("Verified"), len(subs))),
	]
	weights = {"on_time": s.weight_on_time, "quality": s.weight_quality, "rework": s.weight_rework, "safety": s.weight_safety,
		"material": s.weight_material, "response": s.weight_response, "commercial": s.weight_commercial}
	rows, num, den = [], 0, 0
	for key, label, score, basis in ind:
		w = flt(weights.get(key))
		rows.append({"key": key, "label": label, "score": score, "weight": w, "basis": basis})
		if score is not None and w > 0:
			num += score * w
			den += w
	return {"score": round(num / den, 1) if den else None, "indicators": rows,
		"work_orders": {"total": len(wos), "completed": len(done), "ongoing": len([w for w in wos if w.status in WORKING]),
			"delayed": len([w for w in wos if w.status in WORKING and w.expected_completion_date and getdate(w.expected_completion_date) < today])}}


def compliance_alerts():
	"""Daily: refresh compliance document status and tell each subcontractor about documents expiring soon or expired."""
	alert = cint(settings().compliance_alert_days or 30)
	from thinknxg_rental.services.subcontract_portal import notify_supplier

	for r in frappe.get_all("Subcontractor Compliance Document", filters={"parenttype": "Supplier", "expiry_date": ["is", "set"]},
			fields=["name", "parent", "document_type", "expiry_date", "compliance_status"]):
		status = compliance_status(r.expiry_date, alert)
		if status != r.compliance_status:
			frappe.db.set_value("Subcontractor Compliance Document", r.name, "compliance_status", status, update_modified=False)
			if status in ("Expiring", "Expired"):
				notify_supplier(r.parent, _("{0} {1}").format(_(r.document_type), _(status).lower()),
					_("Your {0} expires on {1}. Upload the renewed document in the portal.").format(_(r.document_type), frappe.format(r.expiry_date, "Date")),
					"Supplier", r.parent)
