"""Excess material, its return to the customer, and adjustment against outstanding material.

Three things are kept apart on purpose:

* Physical stock      - ERPNext Stock Entries only (services/stock.py). Excess comes into the Excess
                        Warehouse on the off-hire note (Material Receipt, zero value) and leaves it on an
                        Excess Material Return Note. A Dismantling Entry moves no excess stock.
* Customer balance    - the Rental Ownership Ledger. What the customer still owes is At Site; a
                        Dismantling Entry records an "Adjustment" movement that settles it.
* Commercial record   - the Excess Material Register: one row per off-hire row with excess, with what
                        has been returned to the customer and what has been set against outstanding
                        material. Its balances are recalculated from submitted documents every time.

Item codes are never treated as interchangeable: an adjustment names both items and both quantities.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from thinknxg_rental.services import ledger

REGISTER = "Excess Material Register"
DELIVERED = "Excess from Delivered Items"
UNDELIVERED = "Additional Undelivered Items"
MANAGER_ROLES = ("Rental Manager", "System Manager")
EPS = 1e-6


def is_manager(user=None):
	roles = frappe.get_roles(user or frappe.session.user)
	return any(r in roles for r in MANAGER_ROLES) or (user or frappe.session.user) == "Administrator"


# ----------------------------------------------------------------------------- off-hire note
def excess_category(rental_contract, item_code):
	"""Excess of an item the contract ever dispatched, or of an item it never delivered."""
	dispatched = frappe.db.sql(
		"""select sum(qty) from `tabRental Ownership Ledger`
		where position_type = %s and rental_contract = %s and item_code = %s and movement_type = 'Dispatch'""",
		(ledger.AT_SITE, rental_contract, item_code),
	)[0][0]
	return DELIVERED if flt(dispatched) > 0 else UNDELIVERED


def delivered_qty(rental_contract, item_code):
	return flt(frappe.db.sql(
		"""select sum(qty) from `tabRental Ownership Ledger`
		where position_type = %s and rental_contract = %s and item_code = %s and movement_type = 'Dispatch'""",
		(ledger.AT_SITE, rental_contract, item_code),
	)[0][0])


def make_registers(note, stock_entry):
	"""One register per off-hire row with excess, made once (a row can never be registered twice)."""
	made = []
	for d in note.items:
		if flt(d.excess_qty) <= 0:
			continue
		existing = frappe.db.get_value(REGISTER, {"off_hire_item": d.name}, "name")
		if existing:
			frappe.throw(_("Row #{0}: excess is already registered on {1}").format(d.idx, existing))
		reg = frappe.new_doc(REGISTER)
		reg.update({
			"company": note.company,
			"customer": note.customer,
			"customer_name": note.customer_name,
			"project": note.project,
			"rental_contract": note.rental_contract,
			"rental_site": note.rental_site,
			"posting_date": note.return_date,
			"excess_category": d.excess_category or excess_category(note.rental_contract, d.item_code),
			"item_code": d.item_code,
			"item_name": d.item_name,
			"uom": d.uom,
			"batch_no": d.get("excess_batch_no"),
			"serial_no": d.get("excess_serial_no"),
			"delivered_qty": delivered_qty(note.rental_contract, d.item_code),
			"off_hire_returned_qty": flt(d.returned_qty),
			"excess_qty": flt(d.excess_qty),
			"available_qty": flt(d.excess_qty),
			"hire_off_hire_note": note.name,
			"off_hire_item": d.name,
			"hire_delivery_order": d.delivery_order or ledger.get_last_delivery(note.rental_contract, d.item_code),
			"source_warehouse": d.site_warehouse,
			"excess_warehouse": d.excess_warehouse,
			"stock_entry": stock_entry,
			"status": "Available",
			"remarks": d.remarks,
		})
		reg.flags.from_system = True
		reg.flags.ignore_permissions = True
		reg.insert()
		d.db_set({"excess_register": reg.name, "excess_stock_entry": stock_entry, "adjustment_status": "Available"},
			update_modified=False)
		made.append(reg.name)
	if made:
		note.db_set("excess_status", "Available")
	return made


def registers_of_note(note_name):
	return frappe.get_all(REGISTER, filters={"hire_off_hire_note": note_name}, pluck="name")


def check_note_can_cancel(note):
	"""An off-hire note whose excess has been returned or adjusted cannot be cancelled: cancel those first."""
	regs = registers_of_note(note.name)
	if not regs:
		return
	used = usage(regs)
	blocking = sorted({doc for r in regs for doc in used.get(r, {}).get("documents", [])})
	if blocking:
		frappe.throw(
			_("Its excess material has been returned or adjusted on {0}. Cancel those first.").format(", ".join(blocking)),
			title=_("Excess Material in Use"),
		)


def cancel_registers(note):
	for name in registers_of_note(note.name):
		frappe.db.set_value(REGISTER, name, {"status": "Cancelled", "available_qty": 0}, update_modified=True)
	for d in note.items:
		if d.get("excess_register"):
			d.db_set("adjustment_status", "Cancelled", update_modified=False)
	if note.get("excess_status"):
		note.db_set("excess_status", "Cancelled")


# ----------------------------------------------------------------------------- register balances
def usage(register_names, exclude=None):
	"""{register: {"returned": qty, "adjusted": qty, "documents": [...]}} from submitted documents.
	``exclude``: (doctype, name) left out, for the document being checked."""
	if not register_names:
		return {}
	out = {r: {"returned": 0.0, "adjusted": 0.0, "documents": []} for r in register_names}
	ex_rn = exclude[1] if exclude and exclude[0] == "Excess Material Return Note" else ""
	ex_de = exclude[1] if exclude and exclude[0] == "Dismantling Entry" else ""
	for r in frappe.db.sql(
		"""select i.excess_register as reg, n.name, sum(i.return_qty) as qty
		from `tabExcess Material Return Item` i
		inner join `tabExcess Material Return Note` n on n.name = i.parent and i.parenttype = 'Excess Material Return Note'
		where n.docstatus = 1 and i.excess_register in %(regs)s and n.name != %(ex)s
		group by i.excess_register, n.name""",
		{"regs": tuple(register_names), "ex": ex_rn}, as_dict=True,
	):
		out[r.reg]["returned"] += flt(r.qty)
		out[r.reg]["documents"].append(r.name)
	for r in frappe.db.sql(
		"""select a.excess_register as reg, e.name, sum(a.excess_qty_used) as qty
		from `tabDismantling Adjustment` a
		inner join `tabDismantling Entry` e on e.name = a.parent and a.parenttype = 'Dismantling Entry'
		where e.docstatus = 1 and a.excess_register in %(regs)s and e.name != %(ex)s
		group by a.excess_register, e.name""",
		{"regs": tuple(register_names), "ex": ex_de}, as_dict=True,
	):
		out[r.reg]["adjusted"] += flt(r.qty)
		out[r.reg]["documents"].append(r.name)
	return out


def lock_registers(names):
	"""Row locks on the registers, so two documents using the same excess are checked one after the other."""
	if names:
		frappe.db.sql(f"select name from `tab{REGISTER}` where name in %(n)s for update", {"n": tuple(names)})


def available(register_names, exclude=None):
	"""{register: available qty} = received - returned to customer - adjusted (submitted documents only).
	A cancelled register has nothing available."""
	regs = frappe.get_all(REGISTER, filters={"name": ["in", list(register_names)]}, fields=["name", "excess_qty", "status"])
	used = usage([r.name for r in regs], exclude)
	return {
		r.name: 0.0 if r.status == "Cancelled" else flt(r.excess_qty) - used[r.name]["returned"] - used[r.name]["adjusted"]
		for r in regs
	}


def register_status(excess, returned, adjusted):
	avail = flt(excess) - flt(returned) - flt(adjusted)
	if avail <= EPS:
		return "Closed"
	if returned > EPS and adjusted > EPS:
		return "Partly Settled"
	if returned > EPS:
		return "Partly Returned"
	if adjusted > EPS:
		return "Partly Adjusted"
	return "Available"


def recompute(register_names):
	"""Recalculate the registers' balances and status, and the excess status on their off-hire notes."""
	register_names = [r for r in set(register_names or []) if r]
	if not register_names:
		return
	used = usage(register_names)
	notes = set()
	for reg in frappe.get_all(REGISTER, filters={"name": ["in", register_names]},
			fields=["name", "excess_qty", "status", "hire_off_hire_note", "off_hire_item"]):
		returned, adjusted = used[reg.name]["returned"], used[reg.name]["adjusted"]
		if reg.status == "Cancelled":
			continue
		status = register_status(reg.excess_qty, returned, adjusted)
		frappe.db.set_value(REGISTER, reg.name, {
			"returned_to_customer_qty": returned,
			"adjusted_qty": adjusted,
			"available_qty": flt(reg.excess_qty) - returned - adjusted,
			"status": status,
		})
		if reg.off_hire_item:
			frappe.db.set_value("Hire Off-Hire Item", reg.off_hire_item, "adjustment_status", status, update_modified=False)
		notes.add(reg.hire_off_hire_note)
	for note in notes:
		statuses = frappe.get_all(REGISTER, filters={"hire_off_hire_note": note, "status": ["!=", "Cancelled"]}, pluck="status")
		if not statuses:
			continue
		if all(s == "Closed" for s in statuses):
			value = "Settled"
		elif any(s != "Available" for s in statuses):
			value = "Partly Settled"
		else:
			value = "Available"
		frappe.db.set_value("Hire Off-Hire Note", note, "excess_status", value, update_modified=False)


# ----------------------------------------------------------------------------- outstanding at site
def contract_movements(rental_contract, ownership=None):
	"""{item_code: {delivered, returned, lost, adjusted, outstanding}} from the At Site ledger."""
	conditions, values = ["position_type = %(pt)s", "rental_contract = %(rc)s"], {"pt": ledger.AT_SITE, "rc": rental_contract}
	if ownership:
		conditions.append("ownership = %(own)s")
		values["own"] = ownership
	out = {}
	for r in frappe.db.sql(
		f"""select item_code, movement_type, sum(qty) as qty from `tabRental Ownership Ledger`
		where {" and ".join(conditions)} group by item_code, movement_type""",
		values, as_dict=True,
	):
		row = out.setdefault(r.item_code, frappe._dict(delivered=0.0, returned=0.0, lost=0.0, adjusted=0.0, outstanding=0.0))
		qty = flt(r.qty)
		if r.movement_type == "Dispatch":
			row.delivered += qty
		elif r.movement_type == "Return":
			row.returned -= qty
		elif r.movement_type == "Loss":
			row.lost -= qty
		elif r.movement_type == "Adjustment":
			row.adjusted -= qty
		row.outstanding += qty
	return out


def own_outstanding(rental_contract):
	"""{item_code: qty} of own material still at site (what a Dismantling Entry may settle)."""
	return {k[0]: q for k, q in ledger.get_site_balance(rental_contract).items() if k[1] == "Own" and q > EPS}


# ----------------------------------------------------------------------------- reconciliation
def reconcile(rental_contract):
	"""Everything that must be true before a contract (or its project) is closed, from submitted
	transactions. Returns {"items": [...], "excess": [...], "issues": [...], "reconciled": bool}."""
	items = []
	issues = []
	for item_code, m in sorted(contract_movements(rental_contract).items()):
		items.append(dict(m, item_code=item_code, item_name=frappe.get_cached_value("Item", item_code, "item_name")))
		if m.outstanding > EPS:
			issues.append(_("{0}: {1} delivered, {2} returned, {3} lost, {4} adjusted - {5} still outstanding").format(
				item_code, _q(m.delivered), _q(m.returned), _q(m.lost), _q(m.adjusted), _q(m.outstanding)))

	regs = frappe.get_all(REGISTER, filters={"rental_contract": rental_contract, "status": ["!=", "Cancelled"]},
		fields=["name", "item_code", "item_name", "excess_qty", "excess_warehouse", "stock_entry", "hire_off_hire_note", "status"],
		order_by="creation")
	used = usage([r.name for r in regs])
	excess = []
	for r in regs:
		u = used[r.name]
		avail = flt(r.excess_qty) - u["returned"] - u["adjusted"]
		excess.append(dict(register=r.name, item_code=r.item_code, item_name=r.item_name, excess_qty=flt(r.excess_qty),
			returned_qty=u["returned"], adjusted_qty=u["adjusted"], available_qty=avail, excess_warehouse=r.excess_warehouse,
			hire_off_hire_note=r.hire_off_hire_note))
		if not r.stock_entry or frappe.db.get_value("Stock Entry", r.stock_entry, "docstatus") != 1:
			issues.append(_("{0}: the excess transfer into the excess warehouse is missing").format(r.name))
		if avail > EPS:
			issues.append(_("{0}: {1} {2} of excess material is held for the customer - return it or adjust it").format(
				r.name, _q(avail), r.item_code))
	issues.extend(excess_stock_issues(excess))

	drafts = []
	for doctype in ("Dismantling Entry", "Excess Material Return Note"):
		drafts += [(doctype, n) for n in frappe.get_all(doctype, filters={"rental_contract": rental_contract, "docstatus": 0}, pluck="name")]
	drafts += [("Hire Off-Hire Note", n) for n in frappe.db.sql_list(
		"""select distinct n.name from `tabHire Off-Hire Note` n inner join `tabHire Off-Hire Item` i on i.parent = n.name
		where n.rental_contract = %s and n.docstatus = 0 and (i.excess_qty > 0 or i.received_qty > 0)""", rental_contract)]
	for doctype, name in drafts:
		issues.append(_("{0} {1} is still a draft: submit or delete it").format(_(doctype), name))
	for name in frappe.get_all("Dismantling Entry", filters={"rental_contract": rental_contract, "docstatus": 1,
			"approved_by": ["is", "not set"]}, pluck="name"):
		issues.append(_("Dismantling Entry {0} has no approver").format(name))

	exception = frappe.db.get_value("Rental Contract", rental_contract,
		["reconciliation_exception", "reconciliation_exception_reason", "reconciliation_exception_by", "reconciliation_exception_on"], as_dict=True) or {}
	return {
		"items": items,
		"excess": excess,
		"issues": issues,
		"reconciled": not issues,
		"exception": exception if cint(exception.get("reconciliation_exception")) else None,
	}


def excess_stock_issues(excess_rows):
	"""The excess warehouse must hold at least what the registers say is available (all customers)."""
	issues = []
	pairs = {(r["item_code"], r["excess_warehouse"]) for r in excess_rows if r["available_qty"] > EPS and r["excess_warehouse"]}
	for item_code, warehouse in sorted(pairs):
		held = flt(frappe.db.sql(
			f"""select sum(available_qty) from `tab{REGISTER}`
			where item_code = %s and excess_warehouse = %s and status != 'Cancelled'""", (item_code, warehouse))[0][0])
		in_stock = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
		if in_stock + EPS < held:
			issues.append(_("{0} holds {1} {2}, but the excess registers show {3} available").format(
				warehouse, _q(in_stock), item_code, _q(held)))
	return issues


def set_contract_status(rental_contract, result=None):
	result = result or reconcile(rental_contract)
	status = "Reconciled" if result["reconciled"] else ("Exception Approved" if result["exception"] else "Not Reconciled")
	frappe.db.set_value("Rental Contract", rental_contract, "reconciliation_status", status, update_modified=False)
	return status


def check_can_close(rental_contract):
	"""Refuse to close a contract that is not reconciled, unless a Rental Manager approved an exception."""
	result = reconcile(rental_contract)
	set_contract_status(rental_contract, result)
	if result["reconciled"] or result["exception"]:
		return result
	frappe.throw(
		_("Contract {0} is not reconciled:").format(rental_contract) + "<ul>" + "".join(f"<li>{frappe.utils.escape_html(i)}</li>" for i in result["issues"]) + "</ul>"
		+ _("Settle these, or ask a Rental Manager to approve a reconciliation exception."),
		title=_("Material Reconciliation"),
	)


def approve_exception(rental_contract, reason):
	if not is_manager():
		frappe.throw(_("Only a Rental Manager can approve a reconciliation exception"), frappe.PermissionError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the exception"))
	result = reconcile(rental_contract)
	frappe.db.set_value("Rental Contract", rental_contract, {
		"reconciliation_exception": 1,
		"reconciliation_exception_reason": reason,
		"reconciliation_exception_by": frappe.session.user,
		"reconciliation_exception_on": now_datetime(),
		"reconciliation_status": "Reconciled" if result["reconciled"] else "Exception Approved",
	})
	doc = frappe.get_doc("Rental Contract", rental_contract)
	doc.add_comment("Info", _("Reconciliation exception approved by {0}: {1}. Open issues: {2}").format(
		frappe.session.user, reason, "; ".join(result["issues"]) or _("none")))
	return result


def clear_exception(rental_contract):
	frappe.db.set_value("Rental Contract", rental_contract, {
		"reconciliation_exception": 0, "reconciliation_exception_reason": None,
		"reconciliation_exception_by": None, "reconciliation_exception_on": None,
	})


def _q(value):
	value = flt(value, 3)
	return str(int(value)) if value == int(value) else str(value)


# ----------------------------------------------------------------------------- Project closure
def project_validate(doc, method=None):
	"""A project is not marked Completed while one of its rental contracts is not reconciled."""
	if doc.status != "Completed":
		return
	before = doc.get_doc_before_save()
	if before and before.status == "Completed":
		return
	problems = []
	for rc in frappe.get_all("Rental Contract", filters={"project": doc.name, "docstatus": 1, "status": ["!=", "Cancelled"]}, pluck="name"):
		result = reconcile(rc)
		set_contract_status(rc, result)
		if not result["reconciled"] and not result["exception"]:
			problems.append((rc, result["issues"]))
	if problems:
		html = "".join(
			f"<p><b>{rc}</b></p><ul>" + "".join(f"<li>{frappe.utils.escape_html(i)}</li>" for i in issues) + "</ul>"
			for rc, issues in problems
		)
		frappe.throw(_("The rental material of this project is not reconciled:") + html
			+ _("Settle these, or ask a Rental Manager to approve a reconciliation exception on the contract."),
			title=_("Material Reconciliation"))
