"""Excess Material Abandonment: a Rental Manager's approval that excess still held for a customer has
been abandoned by them.

A Rental User records it (which registers, how much, on what basis and with what evidence); submitting
it is the approval, so only a Rental Manager can. Once approved:

* the quantity is no longer the customer's: the register's Available drops, so it can no longer be
  returned to them or used on a Dismantling Entry, and it stops blocking the contract's reconciliation;
* it belongs to the company: Available to Convert rises, so it can be moved into rental stock on an
  Excess Material Conversion Entry (a separate, explicit step).

No stock moves (the material stays in the excess warehouse as itself) and the customer's material
balance in the Rental Ownership Ledger is not touched. Cancelling gives the excess back to the customer;
refused while it has already been converted.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate

from thinknxg_rental.services import excess


class ExcessMaterialAbandonment(Document):
	def validate(self):
		self.status = {0: "Draft", 1: "Approved", 2: "Cancelled"}[self.docstatus]
		if not self.items:
			frappe.throw(_("Add at least one excess register"))
		if not (self.reason or "").strip():
			frappe.throw(_("Give the reason the excess is treated as abandoned"))
		names = [d.excess_register for d in self.items]
		if len(set(names)) != len(names):
			frappe.throw(_("An excess register can only be entered once per note"), title=_("Duplicate Row"))
		if self.docstatus == 1:
			excess.lock_registers(names)
		regs = {r.name: r for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]}, fields=["*"])}
		avail = excess.available(names, exclude=(self.doctype, self.name))
		self.total_abandon_qty = 0
		for d in self.items:
			prefix = _("Row #{0}: ").format(d.idx)
			reg = regs.get(d.excess_register)
			if not reg:
				frappe.throw(prefix + _("Excess register {0} not found").format(d.excess_register))
			if reg.status == "Cancelled":
				frappe.throw(prefix + _("{0} was cancelled with its off-hire note").format(reg.name))
			if reg.customer != self.customer or reg.company != self.company:
				frappe.throw(prefix + _("{0} is excess of {1}, not of {2}").format(reg.name, reg.customer, self.customer),
					title=_("Different Customer"))
			if self.project and reg.project != self.project:
				frappe.throw(prefix + _("{0} is excess of project {1}, not {2}").format(reg.name, reg.project or _("(none)"), self.project))
			if self.rental_contract and reg.rental_contract != self.rental_contract:
				frappe.throw(prefix + _("{0} is excess of contract {1}, not {2}").format(reg.name, reg.rental_contract, self.rental_contract))
			d.update({"item_code": reg.item_code, "item_name": reg.item_name, "uom": reg.uom, "hire_off_hire_note": reg.hire_off_hire_note})
			d.available_qty = flt(avail.get(reg.name))
			if flt(d.abandon_qty) <= 0:
				frappe.throw(prefix + _("Abandoned Qty must be more than zero"))
			if flt(d.abandon_qty) > d.available_qty + excess.EPS:
				frappe.throw(prefix + _("{0}: only {1} of {2} is still held for the customer (received, less returned, adjusted or already abandoned)").format(
					reg.name, d.available_qty, frappe.bold(reg.item_code)), title=_("More Than Available"))
			d.balance_qty = d.available_qty - flt(d.abandon_qty)
			self.total_abandon_qty += flt(d.abandon_qty)
		contracts = {regs[d.excess_register].rental_contract for d in self.items}
		projects = {regs[d.excess_register].project for d in self.items}
		if not self.rental_contract and len(contracts) == 1:
			self.rental_contract = contracts.pop()
		if not self.project and len(projects) == 1:
			self.project = projects.pop()

	def before_submit(self):
		if not excess.is_manager():
			frappe.throw(_("Only a Rental Manager can approve excess material as abandoned by the customer"), frappe.PermissionError)

	def on_submit(self):
		self.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
		excess.recompute([d.excess_register for d in self.items])
		for rc in {frappe.db.get_value(excess.REGISTER, d.excess_register, "rental_contract") for d in self.items}:
			frappe.get_doc("Rental Contract", rc).add_comment("Info", _("{0}: excess approved as abandoned by the customer by {1} ({2})").format(
				self.name, frappe.session.user, self.abandonment_basis))

	def before_cancel(self):
		excess.check_adjustment_cancel(self, table="items")

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		excess.recompute([d.excess_register for d in self.items])


@frappe.whitelist()
def make_from_registers(registers, target_doc=None):
	"""A draft note for the given registers, each for what is still held for the customer."""
	import json

	if isinstance(registers, str):
		registers = json.loads(registers) if registers.startswith("[") else [registers]
	frappe.has_permission("Excess Material Abandonment", "create", throw=True)
	for name in registers:
		frappe.has_permission(excess.REGISTER, "read", name, throw=True)
	regs = frappe.get_all(excess.REGISTER, filters={"name": ["in", registers], "status": ["!=", "Cancelled"]}, fields=["*"],
		order_by="posting_date, creation")
	if not regs:
		frappe.throw(_("Select an excess register"))
	if len({r.customer for r in regs}) > 1:
		frappe.throw(_("Select excess registers of one customer"))
	avail = excess.available([r.name for r in regs])
	first = regs[0]
	doc = frappe.new_doc("Excess Material Abandonment")
	doc.update({"company": first.company, "customer": first.customer, "customer_name": first.customer_name, "posting_date": nowdate(),
		"project": first.project if len({r.project for r in regs}) == 1 else None,
		"rental_contract": first.rental_contract if len({r.rental_contract for r in regs}) == 1 else None,
		"hire_off_hire_note": first.hire_off_hire_note if len({r.hire_off_hire_note for r in regs}) == 1 else None})
	for r in regs:
		qty = flt(avail.get(r.name))
		if qty > excess.EPS:
			doc.append("items", {"excess_register": r.name, "item_code": r.item_code, "item_name": r.item_name, "uom": r.uom,
				"hire_off_hire_note": r.hire_off_hire_note, "available_qty": qty, "abandon_qty": qty, "balance_qty": 0})
	if not doc.items:
		frappe.throw(_("Nothing on the selected excess registers is still held for the customer"))
	return doc


@frappe.whitelist()
def make_from_register(source_name: str, target_doc=None):
	return make_from_registers([source_name])


@frappe.whitelist()
def make_from_off_hire(source_name: str, target_doc=None):
	frappe.has_permission("Hire Off-Hire Note", "read", source_name, throw=True)
	names = frappe.get_all(excess.REGISTER, filters={"hire_off_hire_note": source_name, "status": ["!=", "Cancelled"]}, pluck="name")
	return make_from_registers(names)


@frappe.whitelist()
def make_from_contract(source_name: str, target_doc=None):
	frappe.has_permission("Rental Contract", "read", source_name, throw=True)
	names = frappe.get_all(excess.REGISTER, filters={"rental_contract": source_name, "status": ["!=", "Cancelled"]}, pluck="name")
	if not names:
		frappe.throw(_("Contract {0} has no excess material").format(source_name))
	return make_from_registers(names)
