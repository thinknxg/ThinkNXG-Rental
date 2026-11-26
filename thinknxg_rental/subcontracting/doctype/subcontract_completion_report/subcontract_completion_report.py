import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from thinknxg_rental.services import subcontracting as sc


class SubcontractCompletionReport(Document):
	def validate(self):
		swo = sc.work_order_for_document(self, ("Completed",))
		self.company, self.supplier, self.hire_order_contract = swo.company, swo.supplier, swo.hire_order_contract
		other = frappe.db.exists("Subcontract Completion Report", {"subcontract_work_order": self.subcontract_work_order, "docstatus": 1, "name": ["!=", self.name]})
		if other:
			frappe.throw(_("{0} is already certified by {1}").format(self.subcontract_work_order, other))
		self.certified_value = sum(flt(r.accepted_qty) * flt(r.rate) for r in frappe.get_all("Subcontract Work Item",
			filters={"parent": self.subcontract_work_order}, fields=["accepted_qty", "rate"]))

	def before_submit(self):
		sc.require_role(sc.SITE_ENGINEER, sc.MANAGER)
		sc.lock_work_order(self.subcontract_work_order)
		self.validate()
		self.certified_by = frappe.session.user

	def on_submit(self):
		sc.set_status(self.subcontract_work_order, "Pending Final Verification")

	def before_cancel(self):
		sc.require_role(sc.MANAGER)
		status = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "status")
		if status in ("Verified", "Closed"):
			frappe.throw(_("The work order is {0} and can no longer be reopened").format(status))

	def on_cancel(self):
		sc.set_status(self.subcontract_work_order, "Completed")
