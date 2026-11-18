"""Excess material handed back to the customer: out of the excess warehouse, against its registers."""
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from thinknxg_rental.services import excess, stock
from thinknxg_rental.services import warehouses as rw


class ExcessMaterialReturnNote(Document):
	def validate(self):
		self.status = {0: "Draft", 1: "Returned", 2: "Cancelled"}[self.docstatus]
		if not self.items:
			frappe.throw(_("Add at least one excess register to return"))
		names = [d.excess_register for d in self.items]
		if len(set(names)) != len(names):
			frappe.throw(_("An excess register can only be entered once per return note"), title=_("Duplicate Row"))
		if self.docstatus == 1:
			excess.lock_registers(names)
		regs = {r.name: r for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]},
			fields=["name", "customer", "project", "rental_contract", "excess_warehouse", "item_code", "item_name", "uom",
				"hire_off_hire_note", "status", "company"])}
		avail = excess.available(names, exclude=(self.doctype, self.name))
		self.total_return_qty = 0
		for d in self.items:
			prefix = _("Row #{0}: ").format(d.idx)
			reg = regs.get(d.excess_register)
			if not reg:
				frappe.throw(prefix + _("Excess register {0} not found").format(d.excess_register))
			if reg.status == "Cancelled":
				frappe.throw(prefix + _("{0} was cancelled with its off-hire note").format(reg.name))
			if reg.customer != self.customer:
				frappe.throw(prefix + _("{0} is excess of customer {1}, not {2}").format(reg.name, reg.customer, self.customer),
					title=_("Different Customer"))
			if reg.company != self.company:
				frappe.throw(prefix + _("{0} belongs to company {1}").format(reg.name, reg.company))
			if not self.source_warehouse:
				self.source_warehouse = reg.excess_warehouse
			if reg.excess_warehouse != self.source_warehouse:
				frappe.throw(prefix + _("{0} is held in {1}, not in {2}. Return material from one warehouse per note.").format(
					reg.name, reg.excess_warehouse, self.source_warehouse))
			d.update({"item_code": reg.item_code, "item_name": reg.item_name, "uom": reg.uom,
				"hire_off_hire_note": reg.hire_off_hire_note, "source_warehouse": reg.excess_warehouse})
			d.available_qty = flt(avail.get(reg.name))
			if flt(d.return_qty) <= 0:
				frappe.throw(prefix + _("Return Qty must be more than zero"))
			if flt(d.return_qty) > d.available_qty + excess.EPS:
				frappe.throw(prefix + _("{0}: only {1} of {2} is available to return (received, less already returned or adjusted)").format(
					reg.name, d.available_qty, frappe.bold(reg.item_code)), title=_("More Than Available"))
			d.balance_qty = d.available_qty - flt(d.return_qty)
			self.total_return_qty += flt(d.return_qty)
		if self.target_warehouse:
			if self.target_warehouse == self.source_warehouse:
				frappe.throw(_("To Warehouse cannot be the excess warehouse itself"))
			if rw.is_site_warehouse(self.target_warehouse) or self.target_warehouse in rw.get_warehouses(rw.CROSS_HIRE, active_only=False):
				frappe.throw(_("{0} is a customer site or cross hire warehouse: excess material cannot be moved there").format(
					frappe.bold(self.target_warehouse)))
		projects = {regs[d.excess_register].project for d in self.items}
		contracts = {regs[d.excess_register].rental_contract for d in self.items}
		if not self.project and len(projects) == 1:
			self.project = projects.pop()
		if not self.rental_contract and len(contracts) == 1:
			self.rental_contract = contracts.pop()

	def on_submit(self):
		purpose = "Material Transfer" if self.target_warehouse else "Material Issue"
		rows = [{"item_code": d.item_code, "qty": d.return_qty, "s_warehouse": self.source_warehouse,
			"t_warehouse": self.target_warehouse, "zero_value": True, "batch_no": d.batch_no, "serial_no": d.serial_no}
			for d in self.items]
		self.db_set({"stock_entry": stock.make_stock_entry(self, purpose, rows, self.posting_date,
			remarks=f"Excess material returned to customer {self.customer} - {self.name}"), "status": "Returned"})
		excess.recompute([d.excess_register for d in self.items])

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		self.db_set("status", "Cancelled")
		excess.recompute([d.excess_register for d in self.items])


def _available_registers(filters):
	filters = dict(filters, status=["not in", ["Closed", "Cancelled"]])
	names = frappe.get_all(excess.REGISTER, filters=filters, pluck="name", order_by="posting_date, creation")
	avail = excess.available(names)
	return [n for n in names if avail.get(n, 0) > excess.EPS], avail


@frappe.whitelist()
def make_from_registers(registers):
	"""A draft return note for the given registers, each for what is still available."""
	if isinstance(registers, str):
		registers = json.loads(registers)
	for name in registers:
		frappe.has_permission(excess.REGISTER, "read", name, throw=True)
	regs = frappe.get_all(excess.REGISTER, filters={"name": ["in", registers]}, fields=["*"], order_by="posting_date, creation")
	if not regs:
		frappe.throw(_("Select an excess register"))
	if len({r.customer for r in regs}) > 1:
		frappe.throw(_("Select excess registers of one customer"))
	avail = excess.available([r.name for r in regs])
	doc = frappe.new_doc("Excess Material Return Note")
	first = regs[0]
	doc.update({"company": first.company, "customer": first.customer, "customer_name": first.customer_name,
		"project": first.project, "rental_contract": first.rental_contract, "posting_date": nowdate(),
		"source_warehouse": first.excess_warehouse})
	if len({r.hire_off_hire_note for r in regs}) == 1:
		doc.hire_off_hire_note = first.hire_off_hire_note
	for r in regs:
		qty = flt(avail.get(r.name))
		if qty <= excess.EPS or r.excess_warehouse != first.excess_warehouse:
			continue
		doc.append("items", {"excess_register": r.name, "item_code": r.item_code, "item_name": r.item_name, "uom": r.uom,
			"hire_off_hire_note": r.hire_off_hire_note, "source_warehouse": r.excess_warehouse, "available_qty": qty,
			"return_qty": qty, "balance_qty": 0, "batch_no": r.batch_no, "serial_no": r.serial_no})
	if not doc.items:
		frappe.throw(_("Nothing is available to return on the selected excess registers"))
	return doc


@frappe.whitelist()
def make_from_off_hire(source_name: str, target_doc=None):
	frappe.has_permission("Hire Off-Hire Note", "read", source_name, throw=True)
	names, _avail = _available_registers({"hire_off_hire_note": source_name})
	if not names:
		frappe.throw(_("This off-hire note has no excess material left to return"))
	return make_from_registers(names)


@frappe.whitelist()
def get_excess_items(customer: str, project: str | None = None, rental_contract: str | None = None,
		hire_off_hire_note: str | None = None, source_warehouse: str | None = None):
	"""Available excess registers of a customer, for the Get Excess Items button."""
	frappe.has_permission("Excess Material Return Note", "create", throw=True)
	filters = {"customer": customer}
	for field, value in (("project", project), ("rental_contract", rental_contract), ("hire_off_hire_note", hire_off_hire_note),
			("excess_warehouse", source_warehouse)):
		if value:
			filters[field] = value
	names, avail = _available_registers(filters)
	out = []
	for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]}, fields=["*"], order_by="posting_date, creation"):
		out.append({"excess_register": r.name, "item_code": r.item_code, "item_name": r.item_name, "uom": r.uom,
			"hire_off_hire_note": r.hire_off_hire_note, "source_warehouse": r.excess_warehouse, "available_qty": avail[r.name],
			"return_qty": avail[r.name], "balance_qty": 0, "batch_no": r.batch_no, "serial_no": r.serial_no})
	return out


@frappe.whitelist()
def get_history(register: str | None = None, hire_off_hire_note: str | None = None, rental_contract: str | None = None):
	"""Every return and adjustment of the selected excess, newest first (the Adjustment History view)."""
	filters = {}
	if register:
		filters["name"] = register
	if hire_off_hire_note:
		filters["hire_off_hire_note"] = hire_off_hire_note
	if rental_contract:
		filters["rental_contract"] = rental_contract
	if not filters:
		frappe.throw(_("Choose what to show the history of"))
	regs = frappe.get_list(excess.REGISTER, filters=filters, fields=["name", "item_code", "excess_qty", "available_qty", "status"])
	names = [r.name for r in regs]
	rows = []
	if names:
		rows += frappe.db.sql(
			"""select 'Excess Material Return Note' as doctype, n.name, n.posting_date, n.docstatus, i.excess_register,
				i.item_code, i.return_qty as qty, null as outstanding_item, null as settled_qty, n.owner
			from `tabExcess Material Return Item` i inner join `tabExcess Material Return Note` n on n.name = i.parent
			where i.excess_register in %(r)s and n.docstatus > 0""", {"r": tuple(names)}, as_dict=True)
		rows += frappe.db.sql(
			"""select 'Dismantling Entry' as doctype, e.name, e.posting_date, e.docstatus, a.excess_register,
				a.excess_item as item_code, a.excess_qty_used as qty, a.outstanding_item, a.adjustment_qty as settled_qty, e.approved_by as owner
			from `tabDismantling Adjustment` a inner join `tabDismantling Entry` e on e.name = a.parent
			where a.excess_register in %(r)s and e.docstatus > 0""", {"r": tuple(names)}, as_dict=True)
	rows.sort(key=lambda r: (str(r.posting_date), r.name), reverse=True)
	return {"registers": regs, "history": rows}
