"""Subcontracting of Hire Order Contracts: allocation, status and cost rules shared by the Subcontracting documents.

Allocation rule (the heart of the module). For every job line of a Hire Order Contract

    available = contract quantity of the line - quantity on SUBMITTED Subcontract Work Orders

A Draft or Pending Approval work order does not use up quantity; a cancelled one gives it back. The check runs
on the server while the Hire Order Contract row is locked, so two work orders submitted at the same time cannot
allocate the same remaining quantity.
"""
import frappe
from frappe import _
from frappe.utils import flt

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
	if doc.docstatus != 1 or doc.status in ("Pending Final Verification", "Verified", "Closed", "Cancelled"):
		return doc.status
	rows = doc.items
	if rows and all(flt(r.accepted_qty) >= flt(r.qty) - EPS for r in rows):
		status = "Completed"
	elif any(flt(r.accepted_qty) > EPS for r in rows):
		status = "Partially Completed"
	elif any(flt(r.completed_qty) > EPS for r in rows):
		status = "Work In Progress"
	else:
		status = "Approved"
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
