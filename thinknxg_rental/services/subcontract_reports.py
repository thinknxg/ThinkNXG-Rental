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
		sum(w.labour_cost) as labour, sum(w.equipment_cost) as equipment from `tabSubcontract Work Order` w where {w} group by w.hire_order_contract""", v)
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
FILTERS = ("company", "supplier", "hire_order_contract", "status", "from_date", "to_date")


def run(name, filters=None):
	if not frappe.has_permission("Subcontract Work Order", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	func, _dt = REPORTS[name]
	return func(frappe._dict(filters or {}))
