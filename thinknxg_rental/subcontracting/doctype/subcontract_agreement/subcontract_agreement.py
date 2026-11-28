import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, nowdate

from thinknxg_rental.services import subcontracting as sc


class SubcontractAgreement(Document):
	"""Rate contract with a subcontractor. Submitting = approval (only through `approve`). Work orders that link it copy its
	rates into their own rows, so the approved commercial terms of a work order never move when the agreement changes."""

	def validate(self):
		self.protect_status()
		if not frappe.db.get_value("Supplier", self.supplier, "is_subcontractor"):
			frappe.throw(_("{0} is not set up as a Subcontractor").format(self.supplier))
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date"))
		if not self.currency:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")
		for f in ("retention_percentage", "advance_percentage"):
			if not 0 <= flt(self.get(f)) <= 100:
				frappe.throw(_("{0} must be between 0 and 100").format(self.meta.get_label(f)))
		seen = set()
		for r in self.rates:
			if flt(r.rate) < 0:
				frappe.throw(_("Rate card row {0}: rate cannot be negative").format(r.idx))
			if r.item_code in seen:
				frappe.throw(_("Rate card row {0}: {1} is listed twice").format(r.idx, r.item_code))
			seen.add(r.item_code)
		if self.agreement_type in ("Unit Rate", "Labour", "Equipment Hire", "Material Supply", "Time Based") and not self.rates:
			frappe.throw(_("A {0} agreement needs a rate card").format(self.agreement_type))
		if self.agreement_type in ("Fixed Price", "Project Based") and not flt(self.contract_value):
			frappe.throw(_("A {0} agreement needs a Contract Value").format(self.agreement_type))

	def protect_status(self):
		if self.is_new():
			self.status = "Draft"
		elif self.docstatus == 0 and not self.flags.workflow_move:
			self.status = frappe.db.get_value(self.doctype, self.name, "status") or "Draft"

	def before_submit(self):
		if not self.flags.approving:
			frappe.throw(_("An agreement is approved with Approve, not submitted directly"), frappe.PermissionError)
		if frappe.db.get_value("Supplier", self.supplier, "subcontractor_approval_status") != "Approved":
			frappe.throw(_("Subcontractor {0} is not approved").format(self.supplier))

	def on_submit(self):
		status = "Expired" if getdate(self.end_date) < getdate(nowdate()) else "Active"
		self.db_set({"status": status, "approved_by": frappe.session.user, "approved_on": now_datetime()})

	def before_cancel(self):
		sc.require_role(sc.MANAGER)
		live = frappe.get_all("Subcontract Work Order", filters={"agreement": self.name, "docstatus": 1,
			"status": ["not in", ["Closed", "Cancelled"]]}, pluck="name")
		if live:
			frappe.throw(_("Work orders still run under this agreement: {0}. Terminate it instead").format(", ".join(live)))

	def on_cancel(self):
		self.db_set("status", "Cancelled")


def _get(name):
	doc = frappe.get_doc("Subcontract Agreement", name)
	doc.check_permission("read")
	return doc


def _move(doc, status, **extra):
	doc.flags.workflow_move = True
	doc.db_set(dict(status=status, **extra))
	doc.add_comment("Info", _("Status: {0}").format(status))
	return status


@frappe.whitelist()
def submit_for_approval(name):
	sc.require_role(sc.MANAGER, sc.EXECUTIVE)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Draft":
		frappe.throw(_("Only a Draft agreement can be sent for approval"))
	doc.flags.workflow_move = True
	doc.validate()
	return _move(doc, "Pending Approval")


@frappe.whitelist()
def approve(name):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Pending Approval":
		frappe.throw(_("Only an agreement that is Pending Approval can be approved"))
	doc.flags.approving = doc.flags.workflow_move = True
	doc.submit()
	return frappe.db.get_value("Subcontract Agreement", name, "status")


@frappe.whitelist()
def reject(name, reason=None):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 0 or doc.status != "Pending Approval":
		frappe.throw(_("Only an agreement that is Pending Approval can be returned"))
	if reason:
		doc.add_comment("Comment", _("Returned to Draft: {0}").format(reason))
	return _move(doc, "Draft")


@frappe.whitelist()
def terminate(name, reason):
	sc.require_role(sc.MANAGER)
	doc = _get(name)
	if doc.docstatus != 1 or doc.status not in ("Active", "Expired"):
		frappe.throw(_("Only an active or expired agreement can be terminated"))
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for the termination"))
	return _move(doc, "Terminated", terminated_on=nowdate(), termination_reason=reason)


def expire_agreements():
	"""Daily: active agreements past their end date become Expired."""
	for name in frappe.get_all("Subcontract Agreement", filters={"docstatus": 1, "status": "Active", "end_date": ["<", nowdate()]}, pluck="name"):
		frappe.db.set_value("Subcontract Agreement", name, "status", "Expired")
