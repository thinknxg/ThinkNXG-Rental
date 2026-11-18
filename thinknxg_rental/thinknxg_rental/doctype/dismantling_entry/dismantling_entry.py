"""Dismantling Entry: outstanding delivered material settled against the customer's excess material.

On submit, three separate records are made (services/excess.py explains why they stay apart):

* customer balance - an "Adjustment" movement in the Rental Ownership Ledger for each outstanding item:
  the customer no longer owes it, and it stops being billed from the day after the posting date;
* physical stock   - the settled units of the outstanding item are issued out of the customer-site
  warehouse (they will not come back, like lost material). The excess item stays in the excess
  warehouse as itself: no item is converted into another;
* commercial       - the excess registers record how much of each excess item was used.

Cancelling reverses all three.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from thinknxg_rental.services import excess, ledger, stock

EPS = excess.EPS


class DismantlingEntry(Document):
	def validate(self):
		contract = frappe.get_doc("Rental Contract", self.rental_contract)
		if contract.docstatus != 1 or contract.status in ("Completed", "Cancelled"):
			frappe.throw(_("Contract {0} is not live").format(self.rental_contract))
		self.company = self.company or contract.company
		for field in ("customer", "customer_name", "project"):
			self.set(field, contract.get(field))
		self.status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}[self.docstatus]
		self.validate_references()
		self.validate_cross_project()
		submitting = self.docstatus == 1
		if submitting:
			excess.lock_registers([d.excess_register for d in self.adjustments if d.excess_register])
			self.check_billing(contract)
		self.set_balances()
		self.validate_adjustments(submitting)

	# ------------------------------------------------------------------ checks
	def validate_references(self):
		if self.hire_delivery_order:
			rc = frappe.db.get_value("Hire Delivery Order", self.hire_delivery_order, "rental_contract")
			if rc != self.rental_contract:
				frappe.throw(_("Hire Delivery Order {0} is not on contract {1}").format(self.hire_delivery_order, self.rental_contract))
		if self.hire_off_hire_note:
			rc = frappe.db.get_value("Hire Off-Hire Note", self.hire_off_hire_note, "rental_contract")
			if rc != self.rental_contract:
				frappe.throw(_("Off-Hire Note {0} is not on contract {1}").format(self.hire_off_hire_note, self.rental_contract))

	def validate_cross_project(self):
		if not self.allow_cross_project:
			self.cross_project_approved_by = None
			return
		if not (self.cross_project_reason or "").strip():
			frappe.throw(_("Give the reason for using excess from other projects"))
		if self.docstatus == 1 or self.cross_project_approved_by:
			if not excess.is_manager():
				if self.docstatus == 1:
					frappe.throw(_("Only a Rental Manager can approve the use of excess from other projects"), frappe.PermissionError)
				return
			self.cross_project_approved_by = frappe.session.user

	def check_billing(self, contract):
		billed = contract.last_billed_upto
		if billed and getdate(self.posting_date) < getdate(billed):
			frappe.throw(
				_("Contract {0} is already billed up to {1}. Use a posting date on or after it, or cancel the later billing first.").format(
					self.rental_contract, frappe.format(billed, {"fieldtype": "Date"})),
				title=_("Period Already Billed"),
			)

	def scope_filters(self):
		"""Excess this entry may use: same customer; same project (or, without a project, the same
		contract) unless use from other projects is allowed."""
		filters = {"customer": self.customer, "company": self.company, "status": ["not in", ["Closed", "Cancelled"]]}
		if not self.allow_cross_project:
			if self.project:
				filters["project"] = self.project
			else:
				filters["rental_contract"] = self.rental_contract
		return filters

	def in_scope(self, reg):
		if reg.customer != self.customer:
			return _("{0} is excess of customer {1}, not of {2}").format(reg.name, reg.customer, self.customer)
		if reg.company != self.company:
			return _("{0} belongs to company {1}").format(reg.name, reg.company)
		if self.allow_cross_project:
			return None
		if self.project and reg.project != self.project:
			return _("{0} is excess of project {1}, not {2}. Allow excess from other projects (Rental Manager approval) to use it.").format(
				reg.name, reg.project or _("(none)"), self.project)
		if not self.project and reg.rental_contract != self.rental_contract:
			return _("{0} is excess of contract {1}. Allow excess from other projects (Rental Manager approval) to use it.").format(
				reg.name, reg.rental_contract)
		return None

	# ------------------------------------------------------------------ balances
	def set_balances(self):
		"""Outstanding and excess tables, from submitted transactions (never from this entry)."""
		moves = excess.contract_movements(self.rental_contract, ownership="Own")
		outstanding = excess.own_outstanding(self.rental_contract)
		settled = {}
		used = {}
		for d in self.adjustments:
			settled[d.outstanding_item] = settled.get(d.outstanding_item, 0) + flt(d.adjustment_qty)
			used[d.excess_register] = used.get(d.excess_register, 0) + flt(d.excess_qty_used)
		if self.docstatus == 0 or not self.outstanding_items:
			self.set("outstanding_items", [])
			for item_code in sorted(set(outstanding) | set(settled)):
				m = moves.get(item_code) or frappe._dict(delivered=0, returned=0, lost=0, adjusted=0)
				item = frappe.get_cached_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True) or frappe._dict()
				qty = flt(outstanding.get(item_code))
				self.append("outstanding_items", {
					"item_code": item_code, "item_name": item.item_name, "uom": item.stock_uom,
					"delivered_qty": m.delivered, "returned_qty": m.returned, "lost_qty": m.lost, "adjusted_qty": m.adjusted,
					"outstanding_qty": qty, "adjustment_qty": settled.get(item_code, 0), "remaining_qty": qty - settled.get(item_code, 0),
				})
		if self.docstatus == 0 or not self.excess_items:
			names = set(frappe.get_all(excess.REGISTER, filters=self.scope_filters(), pluck="name")) | {r for r in used if r}
			avail = excess.available(names, exclude=(self.doctype, self.name))
			use = excess.usage(list(names), exclude=(self.doctype, self.name))
			self.set("excess_items", [])
			for reg in frappe.get_all(excess.REGISTER, filters={"name": ["in", list(names)]}, fields=["*"], order_by="posting_date, creation"):
				qty = flt(avail.get(reg.name))
				if qty <= EPS and reg.name not in used:
					continue
				self.append("excess_items", {
					"excess_register": reg.name, "hire_off_hire_note": reg.hire_off_hire_note, "item_code": reg.item_code,
					"item_name": reg.item_name, "uom": reg.uom, "project": reg.project, "received_qty": reg.excess_qty,
					"returned_qty": use[reg.name]["returned"], "adjusted_qty": use[reg.name]["adjusted"], "available_qty": qty,
					"adjustment_qty": used.get(reg.name, 0), "remaining_qty": qty - used.get(reg.name, 0),
				})
		self._outstanding, self._settled = outstanding, settled
		self.total_outstanding_qty = sum(flt(v) for v in outstanding.values())
		self.total_adjustment_qty = sum(flt(d.adjustment_qty) for d in self.adjustments)
		self.total_excess_used_qty = sum(flt(d.excess_qty_used) for d in self.adjustments)
		self.remaining_outstanding_qty = self.total_outstanding_qty - self.total_adjustment_qty

	def validate_adjustments(self, submitting):
		if not self.adjustments:
			if submitting:
				frappe.throw(_("Add at least one adjustment row before submitting"), title=_("Nothing to Adjust"))
			return
		names = [d.excess_register for d in self.adjustments if d.excess_register]
		regs = {r.name: r for r in frappe.get_all(excess.REGISTER, filters={"name": ["in", names]}, fields=["*"])}
		avail = excess.available(names, exclude=(self.doctype, self.name))
		cross_hire = {k[0] for k, q in ledger.get_site_balance(self.rental_contract).items() if k[1] == "Cross Hire" and q > EPS}
		pairs, used = set(), {}
		for d in self.adjustments:
			prefix = _("Row #{0}: ").format(d.idx)
			reg = regs.get(d.excess_register)
			if not reg:
				frappe.throw(prefix + _("Excess register {0} not found").format(d.excess_register))
			if reg.status == "Cancelled":
				frappe.throw(prefix + _("{0} was cancelled with its off-hire note").format(reg.name))
			problem = self.in_scope(reg)
			if problem:
				frappe.throw(prefix + problem, title=_("Excess Not Allowed"))
			pair = (d.outstanding_item, d.excess_register)
			if pair in pairs:
				frappe.throw(prefix + _("{0} against {1} is entered twice. Use one row.").format(d.outstanding_item, d.excess_register),
					title=_("Duplicate Adjustment"))
			pairs.add(pair)
			item = frappe.get_cached_value("Item", d.outstanding_item, ["item_name", "stock_uom"], as_dict=True)
			d.update({"outstanding_item_name": item.item_name, "outstanding_uom": item.stock_uom, "excess_item": reg.item_code,
				"excess_item_name": reg.item_name, "excess_uom": reg.uom, "hire_off_hire_note": reg.hire_off_hire_note})
			d.outstanding_qty = flt(self._outstanding.get(d.outstanding_item))
			d.excess_available_qty = flt(avail.get(reg.name))
			if flt(d.adjustment_qty) <= 0 or flt(d.excess_qty_used) <= 0:
				frappe.throw(prefix + _("Enter both the outstanding quantity settled and the excess quantity used"), title=_("Quantities Required"))
			if d.outstanding_item not in self._outstanding:
				reason = _("it is cross-hired (supplier-owned) material") if d.outstanding_item in cross_hire else _("nothing of it is outstanding on {0}").format(self.rental_contract)
				frappe.throw(prefix + _("{0} cannot be adjusted: {1}").format(frappe.bold(d.outstanding_item), reason))
			used[reg.name] = used.get(reg.name, 0) + flt(d.excess_qty_used)
			d.conversion_ratio = flt(d.excess_qty_used) / flt(d.adjustment_qty)
			needs_approval = abs(flt(d.excess_qty_used) - flt(d.adjustment_qty)) > EPS or (d.outstanding_uom or "") != (d.excess_uom or "")
			if not needs_approval:
				d.ratio_approved, d.ratio_approved_by = 0, None
			elif d.ratio_approved:
				if excess.is_manager():
					d.ratio_approved_by = d.ratio_approved_by or frappe.session.user
				elif not d.ratio_approved_by:
					frappe.throw(prefix + _("Only a Rental Manager can approve a ratio other than 1 : 1 or a different unit of measure"),
						frappe.PermissionError)
			else:
				d.ratio_approved_by = None
				if submitting:
					frappe.throw(prefix + _("{0} {1} of {2} is set against {3} {4} of {5}. Quantities or units differ: a Rental Manager must approve the ratio.").format(
						d.excess_qty_used, d.excess_uom, d.excess_item, d.adjustment_qty, d.outstanding_uom, d.outstanding_item),
						title=_("Ratio Approval Required"))
		for item_code, qty in self._settled.items():
			if qty > flt(self._outstanding.get(item_code)) + EPS:
				frappe.throw(_("{0}: settling {1} but only {2} is outstanding").format(frappe.bold(item_code), qty, flt(self._outstanding.get(item_code))),
					title=_("More Than Outstanding"))
		for name, qty in used.items():
			if qty > flt(avail.get(name)) + EPS:
				frappe.throw(_("{0} ({1}): using {2} but only {3} is available (received, less already returned to the customer or adjusted)").format(
					name, regs[name].item_code, qty, flt(avail.get(name))), title=_("More Than Available"))

	# ------------------------------------------------------------------ submit / cancel
	def on_submit(self):
		site = frappe.db.get_value("Rental Contract", self.rental_contract, "rental_site")
		site_warehouse = frappe.db.get_value("Rental Site", site, "site_warehouse")
		by_origin = ledger.get_site_balance_by_origin(self.rental_contract)
		left = {k: q for k, q in by_origin.items() if k[1] == "Own" and q > EPS}
		common = dict(posting_date=self.posting_date, billing_date=add_days(self.posting_date, 1), rental_contract=self.rental_contract,
			customer=self.customer, project=self.project, rental_site=site, ownership="Own", warehouse=site_warehouse,
			source_warehouse=site_warehouse, position_type=ledger.AT_SITE, movement_type="Adjustment")
		issue = []
		for d in self.adjustments:
			need = flt(d.adjustment_qty)
			origins = sorted([(q, k) for k, q in left.items() if k[0] == d.outstanding_item], key=lambda o: (-o[0], o[1][3]))
			for qty, key in origins:
				take = min(need, qty)
				if take <= EPS:
					continue
				ledger.add_entry(self, item_code=d.outstanding_item, qty=-take, origin_warehouse=key[3] or None,
					voucher_detail_no=d.name, **common)
				left[key] -= take
				need -= take
				if need <= EPS:
					break
			if need > EPS:
				frappe.throw(_("Row #{0}: {1} is no longer outstanding in full. Reload and try again.").format(d.idx, d.outstanding_item))
			issue.append({"item_code": d.outstanding_item, "qty": d.adjustment_qty, "s_warehouse": site_warehouse,
				"batch_no": d.batch_no, "serial_no": d.serial_no})
		self.db_set({
			"stock_entry": stock.make_stock_entry(self, "Material Issue", issue, self.posting_date,
				remarks=f"Settled against customer excess material (no stock conversion) - {self.name}"),
			"approved_by": frappe.session.user,
			"approved_on": now_datetime(),
			"status": "Submitted",
		})
		excess.recompute([d.excess_register for d in self.adjustments])
		ledger.update_contract_progress(self.rental_contract)

	def before_cancel(self):
		excess.check_adjustment_cancel(self)
		billed = frappe.db.get_value("Rental Contract", self.rental_contract, "last_billed_upto")
		if billed and getdate(self.posting_date) < getdate(billed):
			frappe.throw(_("Cannot cancel: billing has been generated for periods after this adjustment. Cancel those billing schedules first."))

	def on_cancel(self):
		stock.cancel_stock_entries(self)
		ledger.delete_entries(self.doctype, self.name)
		self.db_set("status", "Cancelled")
		excess.recompute([d.excess_register for d in self.adjustments])
		ledger.update_contract_progress(self.rental_contract)

	@frappe.whitelist()
	def fetch_balances(self):
		"""Refresh the outstanding and excess tables in the form (nothing is saved)."""
		self.check_permission("read")
		if self.docstatus == 0:
			contract = frappe.get_doc("Rental Contract", self.rental_contract)
			for field in ("customer", "customer_name", "project", "company"):
				self.set(field, contract.get(field))
			self.set_balances()
		return self.as_dict()


@frappe.whitelist()
def make_from_contract(source_name: str, target_doc=None):
	frappe.has_permission("Rental Contract", "read", source_name, throw=True)
	doc = frappe.new_doc("Dismantling Entry")
	doc.rental_contract = source_name
	doc.posting_date = nowdate()
	contract = frappe.get_doc("Rental Contract", source_name)
	for field in ("company", "customer", "customer_name", "project"):
		doc.set(field, contract.get(field))
	doc.set_balances()
	return doc


@frappe.whitelist()
def make_from_off_hire(source_name: str, target_doc=None):
	note = frappe.get_doc("Hire Off-Hire Note", source_name)
	note.check_permission("read")
	doc = make_from_contract(note.rental_contract)
	doc.hire_off_hire_note = note.name
	return doc
