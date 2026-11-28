import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9


class SubcontractWorkProgress(Document):
	"""Inspection and certification of work: accepted, rejected and rework quantity per work item. Requested from the
	portal (Inspection Requested, with the quantity the subcontractor submits) or opened by staff; only the accepted
	quantity becomes billable."""

	def validate(self):
		if self.is_new() and not self.inspection_status:
			self.inspection_status = "Under Inspection"
		swo = sc.work_order_for_document(self, sc.WORKING)
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
			if flt(r.accepted_qty) < 0 or flt(r.rejected_qty) < 0 or flt(r.get("rework_qty")) < 0 or flt(r.get("reported_qty")) < 0:
				frappe.throw(_("Row {0}: quantities cannot be negative").format(r.idx))

	def before_submit(self):
		sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()
		if not any(flt(r.accepted_qty) or flt(r.rejected_qty) or flt(r.get("rework_qty")) for r in self.items):
			frappe.throw(_("Enter the accepted, rejected or rework quantity of at least one row"))
		for r in self.items:
			if flt(r.accepted_before) + flt(r.accepted_qty) > flt(r.ordered_qty) + EPS:
				frappe.throw(_("Row {0}: accepted work {1} would exceed the ordered {2}").format(r.idx, flt(r.accepted_before) + flt(r.accepted_qty), r.ordered_qty))
		self.verified_by = frappe.session.user

	def on_submit(self):
		self.apply(1)
		acc = sum(flt(r.accepted_qty) for r in self.items)
		bad = sum(flt(r.rejected_qty) for r in self.items)
		rew = sum(flt(r.get("rework_qty")) for r in self.items)
		result = ("Accepted" if not bad and not rew else "Partially Accepted") if acc > EPS else ("Rework Required" if rew > EPS else "Rejected")
		self.db_set("inspection_status", result)
		from thinknxg_rental.services.subcontract_portal import notify_supplier

		notify_supplier(self.supplier, _("Inspection {0}: {1}").format(self.name, _(result)),
			"<br>".join(x for x in (self.quality_remarks, self.corrective_action) if x), self.doctype, self.name)

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


@frappe.whitelist()
def start_inspection(name, inspector=None, proposed_inspection_date=None):
	sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
	doc = frappe.get_doc("Subcontract Work Progress", name)
	if doc.docstatus != 0 or doc.inspection_status != "Inspection Requested":
		frappe.throw(_("Only a requested inspection can be started"))
	doc.db_set({"inspection_status": "Under Inspection", "inspector": inspector or frappe.session.user,
		"proposed_inspection_date": proposed_inspection_date or doc.proposed_inspection_date})
	from thinknxg_rental.services.subcontract_portal import notify_supplier

	notify_supplier(doc.supplier, _("Inspection {0} scheduled").format(doc.name), _("Inspection date: {0}").format(
		frappe.format(doc.proposed_inspection_date, "Date") if doc.proposed_inspection_date else _("to be confirmed")), doc.doctype, doc.name)
	return "Under Inspection"
