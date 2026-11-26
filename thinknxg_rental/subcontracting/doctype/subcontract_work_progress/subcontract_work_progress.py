import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9


class SubcontractWorkProgress(Document):
	def validate(self):
		swo = sc.work_order_for_document(self, ("Approved", "Work In Progress", "Partially Completed"))
		self.company, self.supplier, self.hire_order_contract = swo.company, swo.supplier, swo.hire_order_contract
		rows = {r.name: r for r in frappe.get_all("Subcontract Work Item", filters={"parent": self.subcontract_work_order},
			fields=["name", "job_type", "work_category", "qty", "accepted_qty"])}
		seen = set()
		for r in self.items:
			src = rows.get(r.swo_item)
			if not src:
				frappe.throw(_("Row {0}: work item does not belong to {1}").format(r.idx, self.subcontract_work_order))
			if r.swo_item in seen:
				frappe.throw(_("Row {0}: work item is repeated").format(r.idx))
			seen.add(r.swo_item)
			r.job_type, r.work_category, r.ordered_qty, r.accepted_before = src.job_type, src.work_category, flt(src.qty), flt(src.accepted_qty)
			if flt(r.accepted_qty) < 0 or flt(r.rejected_qty) < 0:
				frappe.throw(_("Row {0}: quantities cannot be negative").format(r.idx))

	def before_submit(self):
		sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()
		if not any(flt(r.accepted_qty) or flt(r.rejected_qty) for r in self.items):
			frappe.throw(_("Enter the accepted or rejected quantity of at least one row"))
		for r in self.items:
			if flt(r.accepted_before) + flt(r.accepted_qty) > flt(r.ordered_qty) + EPS:
				frappe.throw(_("Row {0}: accepted work {1} would exceed the ordered {2}").format(r.idx, flt(r.accepted_before) + flt(r.accepted_qty), r.ordered_qty))
		self.verified_by = frappe.session.user

	def on_submit(self):
		self.apply(1)

	def before_cancel(self):
		sc.require_role(sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		status = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "status")
		if status in ("Pending Final Verification", "Verified", "Closed"):
			frappe.throw(_("The work order is {0}. Cancel its Completion Report first").format(status))
		for r in self.items:
			now = frappe.db.get_value("Subcontract Work Item", r.swo_item, ["accepted_qty", "invoiced_qty"], as_dict=True)
			if flt(now.accepted_qty) - flt(r.accepted_qty) < flt(now.invoiced_qty) - EPS:
				frappe.throw(_("Row {0}: accepted work has already been invoiced; cancel the settlement first").format(r.idx))

	def on_cancel(self):
		self.apply(-1)

	def apply(self, sign):
		for r in self.items:
			frappe.db.sql("""update `tabSubcontract Work Item` set accepted_qty = ifnull(accepted_qty, 0) + %s, rejected_qty = ifnull(rejected_qty, 0) + %s,
				completed_qty = ifnull(completed_qty, 0) + %s where name = %s""",
				(sign * flt(r.accepted_qty), sign * flt(r.rejected_qty), sign * (flt(r.accepted_qty) + flt(r.rejected_qty)), r.swo_item))
		sc.refresh_status(self.subcontract_work_order)
