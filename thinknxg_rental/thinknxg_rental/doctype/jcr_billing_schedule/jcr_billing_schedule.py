import frappe
from frappe import _
from frappe.model.document import Document


class JCRBillingSchedule(Document):
	"""One row per JCR per billing period. Created by the JCR billing engine; it is what stops a
	period from being invoiced twice."""

	def validate(self):
		if frappe.db.exists(
			"JCR Billing Schedule", {"jcr": self.jcr, "jcr_line": self.jcr_line, "billing_type": self.billing_type, "period_from": self.period_from, "name": ["!=", self.name]}
		):
			frappe.throw(_("JCR {0} already has a billing period starting {1}").format(self.jcr, self.period_from))

	def on_trash(self):
		if self.sales_invoice and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 1:
			frappe.throw(_("Cancel Sales Invoice {0} first").format(self.sales_invoice))

	def after_delete(self):
		from thinknxg_rental.services.jcr_billing import update_jcr_progress

		if frappe.db.exists("Job Completion Report", self.jcr):
			update_jcr_progress(self.jcr)
