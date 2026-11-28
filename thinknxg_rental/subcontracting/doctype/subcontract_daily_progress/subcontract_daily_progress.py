import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, nowdate

from thinknxg_rental.services import subcontracting as sc

EPS = 1e-9


class SubcontractDailyProgress(Document):
	"""What the subcontractor did on a day: quantity done per work item, people and equipment on site, delays. Submitted
	(from the portal or by staff), approved by the site engineer. Approved quantity is *reported* work; only an inspection
	(Subcontract Work Progress) accepts it for billing."""

	def validate(self):
		self.protect_status()
		swo = sc.work_order_for_document(self, sc.WORKING)
		self.supplier, self.company, self.project = swo.supplier, swo.company, swo.project
		self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		if getdate(self.report_date) > getdate(nowdate()):
			frappe.throw(_("Report Date cannot be in the future"))
		rows = {r.name: r for r in frappe.get_all("Subcontract Work Item", filters={"parent": self.subcontract_work_order},
			fields=["name", "job_type", "description", "uom", "qty", "reported_qty"])}
		seen = set()
		for r in self.items:
			src = rows.get(r.swo_item)
			if not src:
				frappe.throw(_("Row {0}: work item does not belong to {1}").format(r.idx, self.subcontract_work_order))
			if r.swo_item in seen:
				frappe.throw(_("Row {0}: work item is repeated").format(r.idx))
			seen.add(r.swo_item)
			r.job_type, r.description, r.uom, r.ordered_qty, r.reported_before = src.job_type, src.description, src.uom, flt(src.qty), flt(src.reported_qty)
			if flt(r.qty_done) < 0:
				frappe.throw(_("Row {0}: quantity cannot be negative").format(r.idx))
			if r.reported_before + flt(r.qty_done) > r.ordered_qty + EPS:
				frappe.throw(_("Row {0}: {1} done so far would be more than the ordered {2}").format(r.idx, r.reported_before + flt(r.qty_done), r.ordered_qty))
		if not any(flt(r.qty_done) for r in self.items) and not self.delay_reported and not (self.subcontractor_remarks or self.blockers):
			frappe.throw(_("Enter the quantity done, or report a delay or blocker"))
		if self.labour_deployed and self.labour_deployed < 0:
			frappe.throw(_("Labour deployed cannot be negative"))

	def protect_status(self):
		if self.is_new():
			self.status = "Draft"
			self.submitted_by = self.submitted_by or frappe.session.user
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"

	def before_submit(self):
		sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()

	def on_submit(self):
		self.apply(1)
		self.db_set({"status": "Approved", "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()})
		status = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "status")
		if status in sc.RELEASED and any(flt(r.qty_done) for r in self.items):
			frappe.db.set_value("Subcontract Work Order", self.subcontract_work_order, {"status": "Work In Progress"})
			frappe.db.set_value("Subcontract Work Order", self.subcontract_work_order, "actual_start_date",
				frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "actual_start_date") or self.report_date)
		if self.source == "Portal":
			from thinknxg_rental.services.subcontract_portal import notify_supplier

			notify_supplier(self.supplier, _("Progress report {0} approved").format(self.name), self.review_remarks or "", self.doctype, self.name)

	def before_cancel(self):
		sc.require_role(sc.MANAGER)

	def on_cancel(self):
		self.apply(-1)
		self.db_set("status", "Cancelled")

	def apply(self, sign):
		for r in self.items:
			frappe.db.sql("update `tabSubcontract Work Item` set reported_qty = greatest(ifnull(reported_qty, 0) + %s, 0) where name = %s",
				(sign * flt(r.qty_done), r.swo_item))


def _get(name):
	doc = frappe.get_doc("Subcontract Daily Progress", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def submit_for_review(name):
	doc = _get(name)
	doc.check_permission("write")
	if doc.docstatus != 0 or doc.status not in ("Draft", "Returned"):
		frappe.throw(_("Only a draft or returned report can be submitted"))
	doc.flags.workflow_move = True
	doc.status = "Submitted"
	doc.save()
	return doc.status


@frappe.whitelist()
def approve(name, review_remarks=None):
	doc = _get(name)
	if doc.docstatus != 0 or doc.status not in ("Draft", "Submitted"):
		frappe.throw(_("Only a draft or submitted report can be approved"))
	if review_remarks is not None:
		doc.review_remarks = review_remarks
	doc.flags.workflow_move = True
	doc.submit()
	return "Approved"


@frappe.whitelist()
def return_for_correction(name, review_remarks):
	sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Submitted":
		frappe.throw(_("Only a submitted report can be returned"))
	if not (review_remarks or "").strip():
		frappe.throw(_("Say what needs correcting"))
	doc.db_set({"status": "Returned", "review_remarks": review_remarks, "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()})
	if doc.source == "Portal":
		from thinknxg_rental.services.subcontract_portal import notify_supplier

		notify_supplier(doc.supplier, _("Progress report {0} returned for correction").format(doc.name), review_remarks, doc.doctype, doc.name)
	return "Returned"
