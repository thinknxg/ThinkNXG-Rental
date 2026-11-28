import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9
ROW_TYPES = ("Extra Work", "Additional Material")            # new work items, billable after inspection
LINE_TYPES = ("Quantity Variation", "Rate Revision")          # change existing work items
CLAIM_TYPES = ("Delay Claim", "Material Shortage Claim", "Other Claim")   # money: one accepted row at the approved amount


class SubcontractVariation(Document):
	"""A change to an approved work order, from the subcontractor (portal) or from staff. Nothing changes until a
	Subcontracting Manager approves (submits) it; then the change is written to the work order and logged on both
	documents. Cancelling reverses it while nothing built on it (acceptance, invoicing) stands in the way."""

	def validate(self):
		self.protect_status()
		swo = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order,
			["docstatus", "status", "supplier", "company", "project", "agreement", "expected_completion_date", "hire_order_contract"], as_dict=True)
		if not swo or swo.docstatus != 1 or swo.status in ("Closed", "Cancelled", "Verified"):
			frappe.throw(_("Variations are raised on an approved work order that is still open"))
		self.supplier, self.company, self.project, self.agreement = swo.supplier, swo.company, swo.project, swo.agreement
		self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		self.current_completion_date = swo.expected_completion_date
		lines = {r.name: r for r in frappe.get_all("Subcontract Work Item", filters={"parent": self.subcontract_work_order},
			fields=["name", "job_type", "description", "qty", "rate", "accepted_qty", "invoiced_qty", "work_category", "uom"])}
		value = 0
		if self.variation_type in ROW_TYPES:
			if not self.items:
				frappe.throw(_("Add the extra work or material lines"))
			for r in self.items:
				r.swo_item = None
				if not r.job_type or flt(r.qty) <= 0 or flt(r.rate) < 0:
					frappe.throw(_("Row {0}: item, a quantity above zero and a rate are required").format(r.idx))
				r.amount = flt(r.qty) * flt(r.rate)
				value += r.amount
		elif self.variation_type in LINE_TYPES:
			if not self.items:
				frappe.throw(_("Add the work items that change"))
			for r in self.items:
				src = lines.get(r.swo_item)
				if not src:
					frappe.throw(_("Row {0}: choose a work item of {1}").format(r.idx, self.subcontract_work_order))
				r.job_type, r.current_qty, r.current_rate = src.job_type, flt(src.qty), flt(src.rate)
				r.description, r.work_category, r.uom = r.description or src.description, src.work_category, src.uom
				if self.variation_type == "Quantity Variation":
					r.rate = r.current_rate
					if flt(r.qty) < max(flt(src.accepted_qty), flt(src.invoiced_qty)) - EPS:
						frappe.throw(_("Row {0}: new quantity cannot be below the {1} already accepted or invoiced").format(
							r.idx, max(flt(src.accepted_qty), flt(src.invoiced_qty))))
					if flt(r.qty) <= 0:
						frappe.throw(_("Row {0}: new quantity must be above zero").format(r.idx))
					r.amount = (flt(r.qty) - r.current_qty) * r.current_rate
				else:
					r.qty = r.current_qty
					if flt(r.rate) < 0:
						frappe.throw(_("Row {0}: rate cannot be negative").format(r.idx))
					# a new rate applies only to quantity not yet invoiced; invoiced work keeps its invoice
					r.amount = (flt(r.rate) - r.current_rate) * (r.current_qty - flt(src.invoiced_qty))
				value += r.amount
		elif self.variation_type in CLAIM_TYPES:
			self.items = []
			if flt(self.claimed_amount) <= 0:
				frappe.throw(_("Enter the claimed amount"))
			value = flt(self.approved_amount) if flt(self.approved_amount) else flt(self.claimed_amount)
		else:
			self.items = []
		if self.variation_type == "Time Extension" and not self.new_completion_date:
			frappe.throw(_("Enter the requested completion date"))
		if self.new_completion_date and self.current_completion_date and getdate(self.new_completion_date) <= getdate(self.current_completion_date):
			frappe.throw(_("The requested completion date must be after the current {0}").format(frappe.format(self.current_completion_date, "Date")))
		if flt(self.approved_amount) < 0:
			frappe.throw(_("Approved amount cannot be negative"))
		self.value_change = value

	def protect_status(self):
		if self.is_new():
			self.status = "Draft"
			self.requested_by = self.requested_by or frappe.session.user
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"
		if self.docstatus == 0 and self.status == "Rejected" and not self.flags.workflow_move:
			frappe.throw(_("A rejected variation cannot be changed. Raise a new one"))

	def before_submit(self):
		sc.require_role(sc.MANAGER)
		if not self.flags.approving:
			frappe.throw(_("A variation is approved with Approve"), frappe.PermissionError)
		if self.variation_type in CLAIM_TYPES and not flt(self.approved_amount):
			frappe.throw(_("Enter the approved amount of the claim"))
		if self.variation_type in CLAIM_TYPES and not frappe.db.get_single_value("Subcontracting Settings", "claim_item"):
			frappe.throw(_("Set the Item for approved claims in Subcontracting Settings"))
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()

	def on_submit(self):
		changes = apply_variation(self)
		self.db_set({"status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime(), "applied_changes": json.dumps(changes, default=str)})
		from thinknxg_rental.services.subcontract_portal import notify_supplier

		notify_supplier(self.supplier, _("Variation {0} approved").format(self.name), self.external_remarks or "", self.doctype, self.name)

	def before_cancel(self):
		sc.require_role(sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)

	def on_cancel(self):
		reverse_variation(self)
		self.db_set("status", "Cancelled")


def _recompute(swo):
	"""Work order totals after rows changed, the same arithmetic as SubcontractWorkOrder.calculate_totals."""
	rows = frappe.get_all("Subcontract Work Item", filters={"parent": swo}, fields=["work_category", "amount", "is_additional"])
	labour = sum(flt(r.amount) for r in rows if r.work_category == "Labour")
	equip = sum(flt(r.amount) for r in rows if r.work_category == "Equipment")
	extra = sum(flt(r.amount) for r in rows if r.is_additional)
	frappe.db.set_value("Subcontract Work Order", swo, {"labour_cost": labour, "equipment_cost": equip, "contract_amount": labour + equip - extra,
		"approved_additional_cost": extra, "final_contract_value": labour + equip, "total_estimated_cost": labour + equip}, update_modified=False)


def _insert_row(swo, values):
	idx = flt(frappe.db.sql("select max(idx) from `tabSubcontract Work Item` where parent = %s", swo)[0][0]) + 1
	row = frappe.get_doc(dict(doctype="Subcontract Work Item", parent=swo, parenttype="Subcontract Work Order", parentfield="items",
		idx=int(idx), docstatus=1, is_additional=1, **values))
	row.amount = flt(row.qty) * flt(row.rate)
	row.db_insert()
	return row.name


def apply_variation(v):
	swo = frappe.get_doc("Subcontract Work Order", v.subcontract_work_order)
	changes = {"rows": [], "lines": [], "completion_date": None}
	if v.variation_type in ROW_TYPES:
		for r in v.items:
			name = _insert_row(swo.name, dict(job_type=r.job_type, item_code=r.job_type, work_category=r.work_category or "Labour", description=r.description
				or _("{0} ({1})").format(v.variation_type, v.name), qty=flt(r.qty), uom=r.uom, rate=flt(r.rate), variation=v.name))
			changes["rows"].append(name)
	elif v.variation_type in CLAIM_TYPES:
		item = frappe.db.get_single_value("Subcontracting Settings", "claim_item")
		name = _insert_row(swo.name, dict(job_type=item, item_code=item, work_category="Labour", description=_("{0} {1}: {2}").format(
			v.variation_type, v.name, (v.description or "")[:120]), qty=1, rate=flt(v.approved_amount), accepted_qty=1, completed_qty=1, variation=v.name))
		changes["rows"].append(name)
	elif v.variation_type in LINE_TYPES:
		for r in v.items:
			old = frappe.db.get_value("Subcontract Work Item", r.swo_item, ["qty", "rate", "hoc_item", "is_additional"], as_dict=True)
			if v.variation_type == "Quantity Variation" and swo.hire_order_contract and old.hoc_item and not old.is_additional:
				sc.lock_contract(swo.hire_order_contract)
				avail = {a.hoc_item: a for a in sc.line_availability(swo.hire_order_contract)}.get(old.hoc_item)
				if avail and flt(r.qty) - flt(old.qty) > flt(avail.available_qty) + EPS:
					frappe.throw(_("Row {0}: only {1} more is available on the Hire Order Contract job line").format(r.idx, avail.available_qty))
			new_qty = flt(r.qty) if v.variation_type == "Quantity Variation" else flt(old.qty)
			new_rate = flt(r.rate) if v.variation_type == "Rate Revision" else flt(old.rate)
			frappe.db.set_value("Subcontract Work Item", r.swo_item, {"qty": new_qty, "rate": new_rate, "amount": new_qty * new_rate}, update_modified=False)
			changes["lines"].append({"name": r.swo_item, "qty": flt(old.qty), "rate": flt(old.rate), "new_qty": new_qty, "new_rate": new_rate})
	if v.new_completion_date:
		changes["completion_date"] = str(swo.expected_completion_date or "")
		frappe.db.set_value("Subcontract Work Order", swo.name, "expected_completion_date", v.new_completion_date, update_modified=False)
	_recompute(swo.name)
	sc.refresh_status(swo.name)
	swo.add_comment("Info", _("Variation {0} ({1}) approved by {2}: contract value {3}{4}").format(
		v.name, v.variation_type, frappe.session.user, "+" if flt(v.value_change) >= 0 else "", frappe.format(v.value_change, "Currency")))
	return changes


def reverse_variation(v):
	changes = json.loads(v.applied_changes or "{}")
	swo = v.subcontract_work_order
	for name in changes.get("rows") or []:
		row = frappe.db.get_value("Subcontract Work Item", name, ["invoiced_qty", "accepted_qty", "variation"], as_dict=True)
		if not row:
			continue
		if flt(row.invoiced_qty) > EPS or (v.variation_type in ROW_TYPES and flt(row.accepted_qty) > EPS):
			frappe.throw(_("Work added by this variation has already been accepted or invoiced; reverse that first"))
		frappe.db.delete("Subcontract Work Item", {"name": name})
	for line in changes.get("lines") or []:
		now = frappe.db.get_value("Subcontract Work Item", line["name"], ["qty", "rate", "accepted_qty", "invoiced_qty"], as_dict=True)
		if not now:
			continue
		if flt(now.qty) != flt(line["new_qty"]) or flt(now.rate) != flt(line["new_rate"]):
			frappe.throw(_("A later variation changed the same work item; cancel it first"))
		if flt(line["qty"]) < max(flt(now.accepted_qty), flt(now.invoiced_qty)) - EPS:
			frappe.throw(_("More than the original quantity has been accepted or invoiced; the variation cannot be reversed"))
		frappe.db.set_value("Subcontract Work Item", line["name"], {"qty": line["qty"], "rate": line["rate"], "amount": flt(line["qty"]) * flt(line["rate"])},
			update_modified=False)
	if changes.get("completion_date") is not None:
		frappe.db.set_value("Subcontract Work Order", swo, "expected_completion_date", changes["completion_date"] or None, update_modified=False)
	_recompute(swo)
	sc.refresh_status(swo)
	frappe.get_doc("Subcontract Work Order", swo).add_comment("Info", _("Variation {0} cancelled and reversed by {1}").format(v.name, frappe.session.user))


def _get(name):
	doc = frappe.get_doc("Subcontract Variation", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def submit_variation(name):
	doc = _get(name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.status != "Draft":
		frappe.throw(_("Only a draft variation can be submitted"))
	doc.flags.workflow_move = True
	doc.status = "Submitted"
	doc.save()
	return doc.status


@frappe.whitelist()
def start_review(name):
	sc.require_role(sc.MANAGER, sc.EXECUTIVE)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Submitted":
		frappe.throw(_("Only a submitted variation can be put under review"))
	doc.db_set("status", "Under Review")
	return "Under Review"


@frappe.whitelist()
def approve(name, approved_amount=None, external_remarks=None):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Draft", "Submitted", "Under Review"):
		frappe.throw(_("This variation cannot be approved now ({0})").format(doc.status))
	if approved_amount is not None:
		doc.approved_amount = flt(approved_amount)
	if external_remarks is not None:
		doc.external_remarks = external_remarks
	doc.flags.approving = doc.flags.workflow_move = True
	doc.submit()
	return "Approved"


@frappe.whitelist()
def reject(name, reason):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Submitted", "Under Review"):
		frappe.throw(_("Only a submitted variation can be rejected"))
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for rejecting the variation"))
	doc.db_set({"status": "Rejected", "rejection_reason": reason, "external_remarks": doc.external_remarks or reason})
	from thinknxg_rental.services.subcontract_portal import notify_supplier

	notify_supplier(doc.supplier, _("Variation {0} rejected").format(doc.name), reason, doc.doctype, doc.name)
	return "Rejected"
