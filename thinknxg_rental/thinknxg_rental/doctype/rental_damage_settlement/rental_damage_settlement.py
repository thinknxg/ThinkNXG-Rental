import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from thinknxg_rental.services import ledger, stock
from thinknxg_rental.services.billing import append_taxes
from thinknxg_rental.services.utils import as_system, get_settings, require_setting

EPS = 1e-6


class RentalDamageSettlement(Document):
	def validate(self):
		self.validate_against_returns()
		self.total_damage_amount = self.total_loss_amount = self.total_salvage_value = 0
		for d in self.items:
			if flt(d.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero").format(d.idx))
			liability = flt(d.liability_percent) if d.liability_percent is not None else 100
			d.amount = max(flt(d.qty) * flt(d.rate) * liability / 100.0 - flt(d.salvage_value), 0)
			if d.classification == "Lost":
				self.total_loss_amount += d.amount
			else:
				self.total_damage_amount += d.amount
			self.total_salvage_value += flt(d.salvage_value)
		self.grand_total = (
			self.total_damage_amount + self.total_loss_amount + flt(self.transport_charges) + flt(self.other_charges)
		)

	# ------------------------------------------------------------------ quantities against the return
	def _note(self):
		if not getattr(self, "_note_doc", None):
			self._note_doc = frappe.get_doc("Hire Off-Hire Note", self.hire_off_hire_note)
		return self._note_doc

	def _by_item(self, doc, field):
		out = {}
		for d in doc.items:
			out[d.item_code] = out.get(d.item_code, 0) + flt(d.get(field))
		return out

	def _other_settled(self):
		"""{(item_code, kind): qty} on the note's other submitted settlements."""
		out = {}
		for r in frappe.db.sql(
			"""select i.item_code, i.classification, sum(i.qty) as qty from `tabRental Damage Settlement Item` i
			inner join `tabRental Damage Settlement` s on s.name = i.parent
			where s.hire_off_hire_note = %s and s.docstatus = 1 and s.name != %s group by i.item_code, i.classification""",
			(self.hire_off_hire_note, self.name or ""), as_dict=True,
		):
			kind = "Lost" if r.classification == "Lost" else "Damaged"
			out[(r.item_code, kind)] = out.get((r.item_code, kind), 0) + flt(r.qty)
		return out

	def validate_against_returns(self):
		"""A settlement covers what the off-hire note and its inspection recorded: Lost up to the note's lost
		units plus own units of the item still at site on the contract (recorded as lost on submit);
		Repairable and Beyond Repair up to the units the note returned. The note's other submitted
		settlements count against the same limits, so nothing is settled twice."""
		note = self._note()
		if note.docstatus != 1:
			frappe.throw(_("Off-Hire Note {0} is not submitted").format(note.name))
		self.rental_contract = note.rental_contract
		if note.inspection_status == "Pending":
			frappe.throw(_("Complete the return inspection of Off-Hire Note {0} first").format(note.name), title=_("Inspection Pending"))
		lost, returned = self._by_item(note, "lost_qty"), self._by_item(note, "returned_qty")
		at_site = {k[0]: q for k, q in ledger.get_site_balance(note.rental_contract).items() if k[1] == "Own" and q > EPS}
		other = self._other_settled()
		# units the note's other settlements recorded as lost have left the site since: they count again here
		recorded = dict(frappe.db.sql(
			"""select i.item_code, sum(i.recorded_loss_qty) from `tabRental Damage Settlement Item` i
			inner join `tabRental Damage Settlement` s on s.name = i.parent
			where s.hire_off_hire_note = %s and s.docstatus = 1 and s.name != %s group by i.item_code""",
			(self.hire_off_hire_note, self.name or "")))
		mine = {}
		for d in self.items:
			kind = "Lost" if d.classification == "Lost" else "Damaged"
			mine[(d.item_code, kind)] = mine.get((d.item_code, kind), 0) + flt(d.qty)
		for (item, kind), qty in mine.items():
			total = qty + flt(other.get((item, kind)))
			if kind == "Lost":
				limit = flt(lost.get(item)) + flt(at_site.get(item)) + flt(recorded.get(item))
				what = _("lost on the off-hire note ({0}) or still at site ({1})").format(flt(lost.get(item)), flt(at_site.get(item)))
			else:
				limit = flt(returned.get(item))
				what = _("returned on the off-hire note ({0})").format(limit)
			if total > limit + EPS:
				frappe.throw(_("{0}: {1} {2} settled (this and other settlements of {3}), but only {4} was {5}").format(
					frappe.bold(item), total, _("lost") if kind == "Lost" else _("damaged"), note.name, limit, what),
					title=_("More Than Returned"))

	# ------------------------------------------------------------------ loss still at site
	def before_submit(self):
		self.set_losses_to_record()

	def set_losses_to_record(self):
		"""Lost units the off-hire note did not record (still at site on the contract): this settlement
		records them as lost, so their rental stops on the same day as the note's (its last billable day)."""
		note = self._note()
		lost = self._by_item(note, "lost_qty")
		other = self._other_settled()
		covered = {item: max(flt(lost.get(item)) - flt(other.get((item, "Lost"))), 0) for item in lost}
		self._recorded_now = {}
		for d in self.items:
			d.recorded_loss_qty = 0
			if d.classification != "Lost":
				continue
			use = min(flt(d.qty), covered.get(d.item_code, 0))
			covered[d.item_code] = covered.get(d.item_code, 0) - use
			rest = flt(d.qty) - use
			if rest <= EPS:
				continue
			if d.ownership == "Cross Hire":
				frappe.throw(_("Row #{0}: {1} of cross-hired {2} is not recorded as lost on Off-Hire Note {3}. Record supplier material as lost on an off-hire note.").format(
					d.idx, rest, frappe.bold(d.item_code), note.name))
			d.recorded_loss_qty = rest
			self._recorded_now[d.item_code] = self._recorded_now.get(d.item_code, 0) + rest
		if self._recorded_now:
			billed = frappe.db.get_value("Rental Contract", note.rental_contract, "last_billed_upto")
			if billed and getdate(note.last_billable_date) < getdate(billed):
				frappe.throw(
					_("Contract {0} is already billed up to {1}, after the last billable date {2} of Off-Hire Note {3}. The lost units would stay billed for those days: cancel the later billing schedule(s) and invoice(s), or raise a credit note, then submit this settlement.").format(
						note.rental_contract, frappe.format(billed, {"fieldtype": "Date"}), frappe.format(note.last_billable_date, {"fieldtype": "Date"}), note.name),
					title=_("Period Already Billed"))

	def record_losses(self):
		rows = [d for d in self.items if flt(d.recorded_loss_qty) > EPS]
		if not rows:
			return
		note = self._note()
		site_warehouse = frappe.db.get_value("Rental Site", note.rental_site, "site_warehouse")
		left = {k: q for k, q in ledger.get_site_balance_by_origin(note.rental_contract).items() if k[1] == "Own" and q > EPS}
		common = dict(posting_date=self.posting_date, billing_date=add_days(note.last_billable_date, 1), rental_contract=note.rental_contract,
			customer=note.customer, project=note.project, rental_site=note.rental_site, ownership="Own", warehouse=site_warehouse,
			source_warehouse=site_warehouse, position_type=ledger.AT_SITE, movement_type="Loss")
		issue = []
		for d in rows:
			need = flt(d.recorded_loss_qty)
			for qty, key in sorted([(q, k) for k, q in left.items() if k[0] == d.item_code], key=lambda o: (-o[0], o[1][3])):
				take = min(need, qty)
				ledger.add_entry(self, item_code=d.item_code, qty=-take, origin_warehouse=key[3] or None, voucher_detail_no=d.name, **common)
				left[key] -= take
				need -= take
				if need <= EPS:
					break
			if need > EPS:
				frappe.throw(_("Row #{0}: only {1} of {2} is still at site on {3}").format(d.idx, flt(d.recorded_loss_qty) - need,
					frappe.bold(d.item_code), note.rental_contract))
			issue.append({"item_code": d.item_code, "qty": d.recorded_loss_qty, "s_warehouse": site_warehouse})
		self.db_set("loss_stock_entry", stock.make_stock_entry(self, "Material Issue", issue, self.posting_date,
			remarks=f"Lost at site, settled on {self.name}"))
		for d in rows:
			d.db_set("recorded_loss_qty", d.recorded_loss_qty, update_modified=False)
		ledger.update_contract_progress(note.rental_contract)

	def on_submit(self):
		self.record_losses()
		self.db_set("status", "To Invoice")

	def before_cancel(self):
		if any(flt(d.recorded_loss_qty) > EPS for d in self.items):
			note = self._note()
			billed = frappe.db.get_value("Rental Contract", note.rental_contract, "last_billed_upto")
			if billed and getdate(note.last_billable_date) < getdate(billed):
				frappe.throw(_("Cannot cancel: the units this settlement recorded as lost would be at site again for periods already billed (up to {0}). Cancel those billing schedules first.").format(
					frappe.format(billed, {"fieldtype": "Date"})))
			if frappe.db.get_value("Rental Contract", note.rental_contract, "status") == "Completed":
				frappe.throw(_("Contract {0} is completed: reopen it before cancelling this settlement").format(note.rental_contract))

	def on_cancel(self):
		if self.loss_stock_entry:
			stock.cancel_stock_entries(self)
			ledger.delete_entries(self.doctype, self.name)
			ledger.update_contract_progress(self._note().rental_contract)
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def make_sales_invoice(settlement: str):
	doc = frappe.get_doc("Rental Damage Settlement", settlement)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the settlement first"))
	if doc.sales_invoice:
		frappe.throw(_("Sales Invoice {0} already exists for this settlement").format(doc.sales_invoice))
	damage_item = require_setting("damage_recovery_item")
	loss_item = require_setting("loss_recovery_item")
	contract = frappe.get_doc("Rental Contract", doc.rental_contract)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": doc.company,
			"customer": doc.customer,
			"posting_date": nowdate(),
			"project": contract.project,
			"cost_center": contract.cost_center,
			"nxg_rental_contract": contract.name,
			"nxg_rental_damage_settlement": doc.name,
			"remarks": _("Damage and loss settlement {0} - Contract {1}").format(doc.name, contract.name),
		}
	)
	settings = get_settings()
	# Repairable material is held in the repair warehouse, beyond-repair material in scrap
	warehouse_for = {"Repairable": settings.repair_warehouse, "Beyond Repair": settings.scrap_warehouse, "Lost": settings.get("lost_warehouse")}
	for d in doc.items:
		if flt(d.amount) <= 0:
			continue
		si.append(
			"items",
			{
				"item_code": loss_item if d.classification == "Lost" else damage_item,
				"item_name": f"{d.classification} - {d.item_name}",
				"description": _("{0}: {1} x {2} ({3}% customer liability)").format(
					d.classification, flt(d.qty), d.item_name, flt(d.liability_percent)
				),
				"qty": d.qty,
				"rate": flt(d.amount) / flt(d.qty),
				"project": contract.project,
				"cost_center": contract.cost_center,
				"nxg_hire_item": d.item_code,
				"warehouse": warehouse_for.get(d.classification),
			},
		)
	for label, amount in (
		(_("Return transport charges"), doc.transport_charges),
		(doc.other_charges_description or _("Other charges"), doc.other_charges),
	):
		if flt(amount) > 0:
			si.append(
				"items",
				{"item_code": damage_item, "item_name": label, "description": label, "qty": 1, "rate": amount,
					"project": contract.project, "cost_center": contract.cost_center},
			)
	if not si.items:
		frappe.throw(_("Nothing to invoice on this settlement"))
	append_taxes(si, "Sales Taxes and Charges Template", contract.taxes_and_charges)
	si.flags.ignore_permissions = True
	with as_system():
		si.insert()
		doc.db_set("sales_invoice", si.name)
		if cint(get_settings().auto_submit_sales_invoice):
			si.submit()
	return si.name
