"""The Subcontracting reports. Each is a script report whose rows come from one query over the Subcontracting documents
(submitted, not cancelled); the report folders only name the definition here."""
import frappe
from frappe import _

from thinknxg_rental.services import subcontract_cost


def C(label, fieldname, fieldtype="Data", options=None, width=120):
	return {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "options": options, "width": width}


def swo_filters(f, alias="w"):
	cond, vals = [f"{alias}.docstatus = 1"], {}
	for key, col in (("company", "company"), ("supplier", "supplier"), ("hire_order_contract", "hire_order_contract"), ("status", "status"), ("project", "project"),
			("customer", "customer")):
		if f.get(key):
			cond.append(f"{alias}.{col} = %({key})s")
			vals[key] = f[key]
	if f.get("from_date"):
		cond.append(f"{alias}.contract_date >= %(from_date)s")
		vals["from_date"] = f["from_date"]
	if f.get("to_date"):
		cond.append(f"{alias}.contract_date <= %(to_date)s")
		vals["to_date"] = f["to_date"]
	return " and ".join(cond), vals


def q(sql, vals):
	return frappe.db.sql(sql, vals, as_dict=True)


SWOL = [C("Work Order", "name", "Link", "Subcontract Work Order", 150), C("Hire Order Contract", "hire_order_contract", "Link", "Hire Order Contract", 150),
	C("Subcontractor", "supplier", "Link", "Supplier", 150), C("Status", "status", width=130)]


def subcontractor_wise(f):
	w, v = swo_filters(f)
	return [C("Subcontractor", "supplier", "Link", "Supplier", 160), C("Name", "supplier_name", width=180), C("Work Orders", "orders", "Int", width=90),
		C("Contract Value", "value", "Currency", width=130), C("Labour", "labour", "Currency", width=120), C("Equipment", "equipment", "Currency", width=120),
		C("In Progress", "open", "Int", width=90), C("Closed", "closed", "Int", width=80)], q(f"""select w.supplier, max(w.supplier_name) as supplier_name, count(*) as orders,
		sum(w.final_contract_value) as value, sum(w.labour_cost) as labour, sum(w.equipment_cost) as equipment,
		sum(w.status not in ('Closed', 'Cancelled')) as open, sum(w.status = 'Closed') as closed from `tabSubcontract Work Order` w where {w} group by w.supplier order by value desc""", v)


def hoc_wise(f):
	w, v = swo_filters(f)
	cols = [C("Hire Order Contract", "hire_order_contract", "Link", "Hire Order Contract", 160), C("Customer", "customer", "Link", "Customer", 150),
		C("Contract Qty", "contract_qty", "Float", width=100), C("Subcontracted Qty", "subcontracted", "Float", width=120), C("Balance", "balance", "Float", width=90),
		C("Subcontractors", "subcontractors", "Int", width=100), C("Work Orders", "orders", "Int", width=90), C("Estimated Cost", "estimated", "Currency", width=120),
		C("Labour", "labour", "Currency", width=110), C("Equipment", "equipment", "Currency", width=110), C("Completion %", "completion", "Percent", width=100)]
	rows = q(f"""select w.hire_order_contract, max(w.customer) as customer, count(*) as orders, count(distinct w.supplier) as subcontractors, sum(w.final_contract_value) as estimated,
		sum(w.labour_cost) as labour, sum(w.equipment_cost) as equipment from `tabSubcontract Work Order` w where {w} and ifnull(w.hire_order_contract, '') != ''
		group by w.hire_order_contract""", v)
	from thinknxg_rental.services import subcontracting as sc
	for r in rows:
		s = sc.subcontract_summary(r.hire_order_contract)
		r.update(contract_qty=s["total_contract_qty"], subcontracted=s["subcontracted_qty"], balance=s["balance_qty"], completion=s["completion_pct"])
	return cols, rows


def outstanding_payments(f):
	cond, v = ["pi.docstatus = 1", "ifnull(pi.subcontract_work_order, '') != ''", "pi.outstanding_amount > 0.0005"], {}
	for key in ("company", "supplier"):
		if f.get(key):
			cond.append(f"pi.{key} = %({key})s")
			v[key] = f[key]
	if f.get("hire_order_contract"):
		cond.append("w.hire_order_contract = %(hire_order_contract)s")
		v["hire_order_contract"] = f["hire_order_contract"]
	return [C("Purchase Invoice", "name", "Link", "Purchase Invoice", 150), C("Work Order", "subcontract_work_order", "Link", "Subcontract Work Order", 150),
		C("Hire Order Contract", "hire_order_contract", "Link", "Hire Order Contract", 150), C("Subcontractor", "supplier", "Link", "Supplier", 150),
		C("Invoice Date", "posting_date", "Date", width=100), C("Due Date", "due_date", "Date", width=100), C("Invoiced", "grand_total", "Currency", width=120),
		C("Outstanding", "outstanding_amount", "Currency", width=120)], q(f"""select pi.name, pi.subcontract_work_order, w.hire_order_contract, pi.supplier, pi.posting_date,
		pi.due_date, pi.grand_total, pi.outstanding_amount from `tabPurchase Invoice` pi join `tabSubcontract Work Order` w on w.name = pi.subcontract_work_order
		where {' and '.join(cond)} order by pi.due_date""", v)


def payments(f):
	cond, v = ["pe.docstatus = 1", "ifnull(pe.subcontract_work_order, '') != ''"], {}
	for key in ("company", "supplier"):
		if f.get(key):
			cond.append(f"pe.{'party' if key == 'supplier' else key} = %({key})s")
			v[key] = f[key]
	if f.get("hire_order_contract"):
		cond.append("w.hire_order_contract = %(hire_order_contract)s")
		v["hire_order_contract"] = f["hire_order_contract"]
	if f.get("from_date"):
		cond.append("pe.posting_date >= %(from_date)s")
		v["from_date"] = f["from_date"]
	if f.get("to_date"):
		cond.append("pe.posting_date <= %(to_date)s")
		v["to_date"] = f["to_date"]
	return [C("Payment Entry", "name", "Link", "Payment Entry", 150), C("Date", "posting_date", "Date", width=100), C("Subcontractor", "party", "Link", "Supplier", 150),
		C("Work Order", "subcontract_work_order", "Link", "Subcontract Work Order", 150), C("Hire Order Contract", "hire_order_contract", "Link", "Hire Order Contract", 150),
		C("Type", "kind", width=90), C("Paid", "paid_amount", "Currency", width=120)], q(f"""select pe.name, pe.posting_date, pe.party, pe.subcontract_work_order, w.hire_order_contract,
		if(exists(select 1 from `tabPayment Entry Reference` r where r.parent = pe.name and r.reference_doctype = 'Purchase Invoice'), 'Invoice', 'Advance') as kind, pe.paid_amount
		from `tabPayment Entry` pe join `tabSubcontract Work Order` w on w.name = pe.subcontract_work_order where {' and '.join(cond)} order by pe.posting_date desc""", v)


def material_reconciliation(f):
	w, v = swo_filters(f)
	return [C("Work Order", "swo", "Link", "Subcontract Work Order", 150), C("Subcontractor", "supplier", "Link", "Supplier", 140), C("Hire Order Contract", "hoc", "Link", "Hire Order Contract", 150),
		C("Item", "item_code", "Link", "Item", 150), C("Issued", "issued", "Float", width=80), C("Installed", "installed", "Float", width=80), C("Returned", "returned", "Float", width=80),
		C("Damaged", "damaged", "Float", width=80), C("Missing", "missing", "Float", width=80), C("Outstanding", "outstanding", "Float", width=90),
		C("Recovery", "recovery", "Currency", width=100)], q(f"""select w.name as swo, w.supplier, w.hire_order_contract as hoc, x.item_code, x.issued, ifnull(y.installed, 0) as installed,
		ifnull(y.returned, 0) as returned, ifnull(y.damaged, 0) as damaged, ifnull(y.missing, 0) as missing,
		x.issued - ifnull(y.installed, 0) - ifnull(y.returned, 0) - ifnull(y.damaged, 0) - ifnull(y.missing, 0) as outstanding, ifnull(y.recovery, 0) as recovery
		from `tabSubcontract Work Order` w
		join (select a.subcontract_work_order, i.item_code, sum(i.qty) as issued from `tabSubcontract Material Item` i join `tabSubcontract Material Allocation` a on a.name = i.parent
			where a.docstatus = 1 group by a.subcontract_work_order, i.item_code) x on x.subcontract_work_order = w.name
		left join (select r.subcontract_work_order, i.item_code, sum(i.installed_qty) as installed, sum(i.returned_qty) as returned, sum(i.damaged_qty) as damaged,
			sum(i.missing_qty) as missing, sum(i.recovery_amount) as recovery from `tabSubcontract Return Item` i join `tabSubcontract Material Return` r on r.name = i.parent
			where r.docstatus = 1 group by r.subcontract_work_order, i.item_code) y on y.subcontract_work_order = w.name and y.item_code = x.item_code
		where {w} order by w.name, x.item_code""", v)


def work_progress(f):
	w, v = swo_filters(f)
	return [C("Work Order", "swo", "Link", "Subcontract Work Order", 150), C("Subcontractor", "supplier", "Link", "Supplier", 140), C("Job Type", "job_type", "Link", "Item", 150),
		C("Category", "work_category", width=80), C("Ordered", "qty", "Float", width=80), C("Reported", "completed_qty", "Float", width=80), C("Accepted", "accepted_qty", "Float", width=80),
		C("Rejected", "rejected_qty", "Float", width=80), C("Invoiced", "invoiced_qty", "Float", width=80), C("Done %", "pct", "Percent", width=80)], q(f"""select w.name as swo, w.supplier, i.job_type,
		i.work_category, i.qty, i.completed_qty, i.accepted_qty, i.rejected_qty, i.invoiced_qty, if(i.qty, i.accepted_qty / i.qty * 100, 0) as pct
		from `tabSubcontract Work Order` w join `tabSubcontract Work Item` i on i.parent = w.name where {w} order by w.name, i.idx""", v)


def pending_completion(f):
	w, v = swo_filters(f)
	return SWOL + [C("Expected Completion", "expected_completion_date", "Date", width=120), C("Value", "final_contract_value", "Currency", width=120)], q(f"""select w.name, w.hire_order_contract, w.supplier,
		w.status, w.expected_completion_date, w.final_contract_value from `tabSubcontract Work Order` w where {w} and w.status in ('Completed', 'Pending Final Verification') order by w.expected_completion_date""", v)


def cost_analysis(f):
	w, v = swo_filters(f)
	return SWOL + [C("Ordered Value", "final_contract_value", "Currency", width=120), C("Labour", "labour_cost", "Currency", width=110), C("Equipment", "equipment_cost", "Currency", width=110),
		C("Additional Work", "additional", "Currency", width=110), C("Certified", "certified", "Currency", width=110), C("Retention Held", "retention", "Currency", width=110),
		C("Penalties", "penalties", "Currency", width=100), C("Recoveries", "recoveries", "Currency", width=100), C("Net Cost", "net_cost", "Currency", width=110)], q(f"""select w.name, w.hire_order_contract,
		w.supplier, w.status, w.final_contract_value, w.labour_cost, w.equipment_cost, w.approved_additional_cost as additional, ifnull(s.certified, 0) as certified, ifnull(s.retention, 0) as retention,
		ifnull(s.penalties, 0) as penalties, ifnull(s.recoveries, 0) as recoveries, ifnull(s.certified, 0) - ifnull(s.penalties, 0) - ifnull(s.recoveries, 0) as net_cost
		from `tabSubcontract Work Order` w left join (select subcontract_work_order, sum(certified_value) as certified, sum(retention_amount) as retention, sum(penalties) as penalties,
			sum(damage_recovery + other_deductions) as recoveries from `tabSubcontract Settlement` where docstatus = 1 group by subcontract_work_order) s on s.subcontract_work_order = w.name
		where {w} order by w.name""", v)


def performance(f):
	w, v = swo_filters(f)
	return [C("Subcontractor", "supplier", "Link", "Supplier", 160), C("Rating", "rating", "Int", width=70), C("Work Orders", "orders", "Int", width=90), C("Completed", "completed", "Int", width=90),
		C("Late", "late", "Int", width=70), C("Accepted Qty", "accepted", "Float", width=100), C("Rejected Qty", "rejected", "Float", width=100), C("Rejection %", "rejection_pct", "Percent", width=100),
		C("Material Recovery", "recovery", "Currency", width=120)], q(f"""select w.supplier, max(s.performance_rating) as rating, count(distinct w.name) as orders,
		count(distinct if(w.status in ('Completed', 'Pending Final Verification', 'Verified', 'Closed'), w.name, null)) as completed,
		count(distinct if(c.completion_date > w.expected_completion_date, w.name, null)) as late, sum(i.accepted_qty) as accepted, sum(i.rejected_qty) as rejected,
		if(sum(i.accepted_qty + i.rejected_qty), sum(i.rejected_qty) / sum(i.accepted_qty + i.rejected_qty) * 100, 0) as rejection_pct,
		(select ifnull(sum(r.total_recovery), 0) from `tabSubcontract Material Return` r where r.docstatus = 1 and r.supplier = w.supplier) as recovery
		from `tabSubcontract Work Order` w join `tabSupplier` s on s.name = w.supplier join `tabSubcontract Work Item` i on i.parent = w.name
		left join `tabSubcontract Completion Report` c on c.subcontract_work_order = w.name and c.docstatus = 1 where {w} group by w.supplier""", v)


def hoc_profitability(f):
	cols = [C("Hire Order Contract", "hire_order_contract", "Link", "Hire Order Contract", 160), C("Customer", "customer", "Link", "Customer", 150), C("Customer Revenue", "customer_revenue", "Currency", width=130),
		C("Labour Cost", "labour_cost", "Currency", width=110), C("Equipment Cost", "equipment_cost", "Currency", width=110), C("Additional Work", "additional_work_cost", "Currency", width=110),
		C("Penalties", "penalties", "Currency", width=100), C("Recoveries", "recoveries", "Currency", width=100), C("Subcontract Cost", "subcontract_cost", "Currency", width=120),
		C("Other Direct Costs", "other_direct_costs", "Currency", width=120), C("Net Profit", "net_profit", "Currency", width=120), C("Margin %", "margin", "Percent", width=90)]
	w, v = swo_filters(f)
	rows = []
	for r in q(f"select w.hire_order_contract, max(w.customer) as customer from `tabSubcontract Work Order` w where {w} group by w.hire_order_contract", v):
		r.update(subcontract_cost.profitability(r.hire_order_contract))
		rows.append(r)
	return cols, rows


def labour_cost(f):
	return _category_cost(f, "Labour")


def equipment_cost(f):
	return _category_cost(f, "Equipment")


def _category_cost(f, category):
	w, v = swo_filters(f)
	v["cat"] = category
	extra = [C("Equipment Is", "equipment_ownership", width=150), C("Cross Hire Order", "cross_hire_order", "Link", "Cross Hire Order", 140)] if category == "Equipment" else []
	sel = ", i.equipment_ownership, i.cross_hire_order" if category == "Equipment" else ""
	return [C("Work Order", "swo", "Link", "Subcontract Work Order", 150), C("Subcontractor", "supplier", "Link", "Supplier", 140), C("Hire Order Contract", "hoc", "Link", "Hire Order Contract", 150),
		C("Job Type", "job_type", "Link", "Item", 150)] + extra + [C("Qty", "qty", "Float", width=80), C("Rate", "rate", "Currency", width=100), C("Ordered Cost", "amount", "Currency", width=120),
		C("Accepted Cost", "accepted_cost", "Currency", width=120), C("Invoiced Cost", "invoiced_cost", "Currency", width=120)], q(f"""select w.name as swo, w.supplier, w.hire_order_contract as hoc, i.job_type{sel},
		i.qty, i.rate, i.amount, i.accepted_qty * i.rate as accepted_cost, i.invoiced_qty * i.rate as invoiced_cost
		from `tabSubcontract Work Order` w join `tabSubcontract Work Item` i on i.parent = w.name where {w} and i.work_category = %(cat)s order by w.name""", v)


def retention_advance(f):
	w, v = swo_filters(f)
	return SWOL + [C("Advance Agreed", "advance_amount", "Currency", width=120), C("Advance Paid", "advance_paid", "Currency", width=120), C("Advance Recovered", "advance_recovered", "Currency", width=130),
		C("Advance Outstanding", "advance_outstanding", "Currency", width=130), C("Retention Held", "retention", "Currency", width=120)], q(f"""select w.name, w.hire_order_contract, w.supplier, w.status, w.advance_amount,
		ifnull(p.paid, 0) as advance_paid, ifnull(s.recovered, 0) as advance_recovered, ifnull(p.paid, 0) - ifnull(s.recovered, 0) as advance_outstanding, ifnull(s.retention, 0) as retention
		from `tabSubcontract Work Order` w
		left join (select pe.subcontract_work_order, sum(pe.paid_amount) as paid from `tabPayment Entry` pe where pe.docstatus = 1 and pe.payment_type = 'Pay'
			and not exists (select 1 from `tabPayment Entry Reference` r where r.parent = pe.name and r.reference_doctype = 'Purchase Invoice') group by pe.subcontract_work_order) p on p.subcontract_work_order = w.name
		left join (select subcontract_work_order, sum(advance_recovery) as recovered, sum(retention_amount) as retention from `tabSubcontract Settlement` where docstatus = 1 group by subcontract_work_order) s
			on s.subcontract_work_order = w.name where {w} and (ifnull(p.paid, 0) + ifnull(s.retention, 0)) > 0 order by w.name""", v)


REPORTS = {
	"Subcontractor Wise Work Orders": (subcontractor_wise, "Subcontract Work Order"),
	"HOC Wise Subcontracting": (hoc_wise, "Subcontract Work Order"),
	"Outstanding Subcontractor Payments": (outstanding_payments, "Subcontract Settlement"),
	"Subcontractor Payments": (payments, "Subcontract Settlement"),
	"Subcontract Material Issue and Return": (material_reconciliation, "Subcontract Material Allocation"),
	"Subcontract Work Progress Report": (work_progress, "Subcontract Work Progress"),
	"Pending Completion Approval": (pending_completion, "Subcontract Work Order"),
	"Subcontract Cost Analysis": (cost_analysis, "Subcontract Work Order"),
	"Subcontractor Performance": (performance, "Subcontract Work Order"),
	"HOC Subcontract Profitability": (hoc_profitability, "Subcontract Work Order"),
	"Subcontract Labour Cost": (labour_cost, "Subcontract Work Order"),
	"Subcontract Equipment Cost": (equipment_cost, "Subcontract Work Order"),
	"Subcontract Retention and Advance Outstanding": (retention_advance, "Subcontract Work Order"),
}
# ----- v2 reports ---------------------------------------------------------------------------------------------------
def register(f):
	"""Subcontractor Register: every subcontractor with classification, approval, compliance, agreements and score."""
	from thinknxg_rental.services import subcontracting as sc

	cond, v = ["s.is_subcontractor = 1"], {}
	if f.get("supplier"):
		cond.append("s.name = %(supplier)s")
		v["supplier"] = f.supplier
	if f.get("status"):
		cond.append("s.subcontractor_approval_status = %(status)s")
		v["status"] = f.status
	rows = q(f"""select s.name as supplier, s.supplier_name, s.business_classification, s.subcontractor_type, s.subcontractor_approval_status as approval,
		s.tax_id, s.service_areas, s.disabled,
		(select count(*) from `tabSubcontract Agreement` a where a.supplier = s.name and a.docstatus = 1 and a.status = 'Active') as agreements,
		(select count(*) from `tabSubcontract Work Order` w where w.supplier = s.name and w.docstatus = 1) as orders,
		(select sum(w.final_contract_value) from `tabSubcontract Work Order` w where w.supplier = s.name and w.docstatus = 1) as value
		from `tabSupplier` s where {' and '.join(cond)} order by s.supplier_name""", v)
	for r in rows:
		docs = frappe.get_all("Subcontractor Compliance Document", filters={"parent": r.supplier, "parenttype": "Supplier"}, fields=["expiry_date"])
		r.compliance = "Expired" if any(sc.compliance_status(d.expiry_date, 0) == "Expired" for d in docs) else (
			"Expiring" if any(sc.compliance_status(d.expiry_date) == "Expiring" for d in docs) else ("Valid" if docs else "None on file"))
		r.score = sc.scorecard(r.supplier)["score"]
	return [C("Subcontractor", "supplier", "Link", "Supplier", 150), C("Name", "supplier_name", width=180), C("Classification", "business_classification", width=150),
		C("Provides", "subcontractor_type", width=90), C("Approval", "approval", width=100), C("Compliance", "compliance", width=100),
		C("Active Agreements", "agreements", "Int", width=110), C("Work Orders", "orders", "Int", width=100), C("Total Value", "value", "Currency", width=130),
		C("Score", "score", "Float", width=80), C("Tax ID", "tax_id", width=120), C("Service Areas", "service_areas", width=180)], rows


def variation_report(f):
	w, v = swo_filters(f)
	return [C("Variation", "name", "Link", "Subcontract Variation", 150), C("Work Order", "subcontract_work_order", "Link", "Subcontract Work Order", 150),
		C("Subcontractor", "supplier", "Link", "Supplier", 150), C("Type", "variation_type", width=150), C("Requested", "request_date", "Date", width=100),
		C("Status", "status", width=100), C("Claimed", "claimed_amount", "Currency", width=120), C("Approved Amount", "approved_amount", "Currency", width=120),
		C("Change in Value", "value_change", "Currency", width=130), C("New Completion", "new_completion_date", "Date", width=110), C("From", "source", width=80),
		C("Approved By", "approved_by", width=140)], q(f"""select x.name, x.subcontract_work_order, x.supplier, x.variation_type, x.request_date, x.status,
		x.claimed_amount, x.approved_amount, x.value_change, x.new_completion_date, x.source, x.approved_by from `tabSubcontract Variation` x
		join `tabSubcontract Work Order` w on w.name = x.subcontract_work_order where {w} and x.docstatus < 2 order by x.request_date desc""", v)


def account_statement(f):
	"""GL of the subcontractor (party ledger): the figures are ERPNext's own accounting entries, so they reconcile."""
	cols = [C("Date", "posting_date", "Date", width=100), C("Voucher Type", "voucher_type", width=130), C("Voucher", "voucher_no", "Dynamic Link", "voucher_type", 160),
		C("Work Order", "work_order", "Link", "Subcontract Work Order", 150), C("Debit (paid / deducted)", "debit", "Currency", width=140),
		C("Credit (invoiced)", "credit", "Currency", width=130), C("Balance Payable", "balance", "Currency", width=130)]
	if not f.get("supplier"):
		return cols, []  # the statement is of one subcontractor: nothing until one is chosen
	company = f.get("company") or frappe.db.get_single_value("Rental Settings", "company")
	v = {"party": f.supplier, "company": company, "from_date": f.get("from_date") or "1900-01-01", "to_date": f.get("to_date") or frappe.utils.nowdate()}
	opening = frappe.utils.flt(frappe.db.sql("""select sum(credit - debit) from `tabGL Entry` where party_type = 'Supplier' and party = %(party)s and company = %(company)s
		and is_cancelled = 0 and posting_date < %(from_date)s""", v)[0][0])
	rows = q("""select posting_date, voucher_type, voucher_no, sum(debit) as debit, sum(credit) as credit, max(against_voucher) as against_voucher
		from `tabGL Entry` where party_type = 'Supplier' and party = %(party)s and company = %(company)s and is_cancelled = 0
		and posting_date between %(from_date)s and %(to_date)s group by posting_date, voucher_type, voucher_no order by posting_date, min(creation)""", v)
	bal = opening
	out = [frappe._dict(voucher_type=_("Opening"), balance=opening)]
	for r in rows:
		bal += frappe.utils.flt(r.credit) - frappe.utils.flt(r.debit)
		r.balance = bal
		r.work_order = frappe.db.get_value(r.voucher_type, r.voucher_no, "subcontract_work_order") if r.voucher_type in ("Purchase Invoice", "Payment Entry") else None
		out.append(r)
	out.append(frappe._dict(voucher_type=_("Closing"), debit=sum(frappe.utils.flt(r.debit) for r in rows), credit=sum(frappe.utils.flt(r.credit) for r in rows), balance=bal))
	return cols, out


def cost_monitor(f):
	from thinknxg_rental.services import subcontracting as sc

	w, v = swo_filters(f)
	rows = q(f"""select w.name, w.supplier, w.project, w.status, w.contract_amount as original, w.final_contract_value as revised,
		(select sum(x.value_change) from `tabSubcontract Variation` x where x.subcontract_work_order = w.name and x.status = 'Approved') as variations,
		(select sum(x.claimed_amount + x.value_change) from `tabSubcontract Variation` x where x.subcontract_work_order = w.name and x.status in ('Submitted', 'Under Review')) as pending,
		(select sum(wi.reported_qty * wi.rate) from `tabSubcontract Work Item` wi where wi.parent = w.name) as completed,
		(select sum(wi.accepted_qty * wi.rate) from `tabSubcontract Work Item` wi where wi.parent = w.name) as certified,
		(select sum(s.certified_value) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as invoiced,
		(select sum(s.retention_amount) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as retention,
		(select sum(s.advance_recovery) from `tabSubcontract Settlement` s where s.subcontract_work_order = w.name and s.docstatus = 1) as advance_recovered,
		(select sum(pi.grand_total - pi.outstanding_amount) from `tabPurchase Invoice` pi where pi.subcontract_work_order = w.name and pi.docstatus = 1) as paid,
		(select sum(pi.outstanding_amount) from `tabPurchase Invoice` pi where pi.subcontract_work_order = w.name and pi.docstatus = 1) as outstanding
		from `tabSubcontract Work Order` w where {w} and w.status != 'Cancelled' order by w.contract_date desc""", v)
	for r in rows:
		r.forecast = frappe.utils.flt(r.revised) + frappe.utils.flt(r.pending)
		r.utilization = round(100 * frappe.utils.flt(r.certified) / frappe.utils.flt(r.revised), 1) if frappe.utils.flt(r.revised) else 0
		r.advance_paid = sc.advance_paid(r.name)[0]
	return [C("Work Order", "name", "Link", "Subcontract Work Order", 150), C("Subcontractor", "supplier", "Link", "Supplier", 140), C("Project", "project", "Link", "Project", 120),
		C("Original", "original", "Currency", width=120), C("Approved Variations", "variations", "Currency", width=130), C("Revised", "revised", "Currency", width=120),
		C("Completed (reported)", "completed", "Currency", width=130), C("Certified", "certified", "Currency", width=120), C("Invoiced", "invoiced", "Currency", width=120),
		C("Paid", "paid", "Currency", width=110), C("Retention", "retention", "Currency", width=110), C("Advance Paid", "advance_paid", "Currency", width=110),
		C("Advance Recovered", "advance_recovered", "Currency", width=120), C("Outstanding", "outstanding", "Currency", width=110),
		C("Utilization %", "utilization", "Percent", width=100), C("Forecast Final Cost", "forecast", "Currency", width=130)], rows


def delayed(f):
	from thinknxg_rental.services import subcontracting as sc

	w, v = swo_filters(f)
	v.update(today=frappe.utils.nowdate(), working=sc.WORKING)
	rows = q(f"""select w.name, w.supplier, w.project, w.status, w.expected_completion_date, datediff(%(today)s, w.expected_completion_date) as days_late,
		w.site_engineer, (select sum(wi.accepted_qty) / nullif(sum(wi.qty), 0) * 100 from `tabSubcontract Work Item` wi where wi.parent = w.name) as progress,
		(select max(d.report_date) from `tabSubcontract Daily Progress` d where d.subcontract_work_order = w.name and d.docstatus = 1) as last_report,
		(select max(d.delay_reason) from `tabSubcontract Daily Progress` d where d.subcontract_work_order = w.name and d.delay_reported = 1) as delay_reason
		from `tabSubcontract Work Order` w where {w} and w.status in %(working)s and w.expected_completion_date < %(today)s order by days_late desc""", v)
	return [C("Work Order", "name", "Link", "Subcontract Work Order", 150), C("Subcontractor", "supplier", "Link", "Supplier", 150), C("Project", "project", "Link", "Project", 120),
		C("Status", "status", width=130), C("Due", "expected_completion_date", "Date", width=100), C("Days Late", "days_late", "Int", width=90),
		C("Progress %", "progress", "Percent", width=90), C("Last Report", "last_report", "Date", width=100), C("Reported Delay", "delay_reason", width=200),
		C("Site Engineer", "site_engineer", width=150)], rows


def invoice_register(f):
	w, v = swo_filters(f)
	return [C("Submission", "name", "Link", "Subcontractor Invoice Submission", 150), C("Supplier Invoice", "supplier_invoice_no", width=130),
		C("Invoice Date", "supplier_invoice_date", "Date", width=100), C("Subcontractor", "supplier", "Link", "Supplier", 150),
		C("Work Order", "subcontract_work_order", "Link", "Subcontract Work Order", 150), C("Bill Type", "bill_type", width=100), C("Status", "status", width=90),
		C("Claimed", "total_claimed", "Currency", width=120), C("Purchase Invoice", "purchase_invoice", "Link", "Purchase Invoice", 150),
		C("Invoice Total", "grand_total", "Currency", width=120), C("Outstanding", "outstanding_amount", "Currency", width=120), C("From", "source", width=80)], q(f"""
		select x.name, x.supplier_invoice_no, x.supplier_invoice_date, x.supplier, x.subcontract_work_order, x.bill_type, x.status, x.total_claimed,
		x.purchase_invoice, pi.grand_total, pi.outstanding_amount, x.source from `tabSubcontractor Invoice Submission` x
		join `tabSubcontract Work Order` w on w.name = x.subcontract_work_order left join `tabPurchase Invoice` pi on pi.name = x.purchase_invoice and pi.docstatus = 1
		where {w} and x.docstatus < 2 order by x.supplier_invoice_date desc""", v)


REPORTS.update({
	"Subcontractor Register": (register, "Supplier"),
	"Subcontract Variation Report": (variation_report, "Subcontract Variation"),
	"Subcontractor Account Statement": (account_statement, "Purchase Invoice"),
	"Subcontract Cost Monitor": (cost_monitor, "Subcontract Work Order"),
	"Delayed Subcontract Work Orders": (delayed, "Subcontract Work Order"),
	"Subcontractor Invoice Register": (invoice_register, "Subcontractor Invoice Submission"),
})


FILTERS = ("company", "supplier", "hire_order_contract", "status", "from_date", "to_date")


def run(name, filters=None):
	if not frappe.has_permission("Subcontract Work Order", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	func, _dt = REPORTS[name]
	return func(frappe._dict(filters or {}))
