import frappe
from frappe import _
from frappe.model.document import Document


class SubcontractMessage(Document):
	"""A message between staff and a subcontractor, shown in the portal. Desk comments on the documents stay internal."""

	def validate(self):
		if self.is_new():
			self.sender = frappe.session.user
			self.sender_name = frappe.utils.get_fullname(frappe.session.user)
		if self.subcontract_work_order:
			sup = frappe.db.get_value("Subcontract Work Order", self.subcontract_work_order, "supplier")
			if sup != self.supplier:
				frappe.throw(_("Work order {0} belongs to another subcontractor").format(self.subcontract_work_order))
		if not (self.message or "").strip():
			frappe.throw(_("Write a message"))

	def after_insert(self):
		if self.direction in ("To Subcontractor", "Announcement"):
			from thinknxg_rental.services.subcontract_portal import notify_supplier

			notify_supplier(self.supplier, self.subject or _("New message"), frappe.utils.escape_html(self.message), self.doctype, self.name)
		elif self.subcontract_work_order:
			from thinknxg_rental.services.subcontract_portal import notify_staff

			notify_staff(self.subcontract_work_order, _("Message from {0}: {1}").format(self.supplier, (self.subject or self.message)[:80]),
				self.doctype, self.name)
