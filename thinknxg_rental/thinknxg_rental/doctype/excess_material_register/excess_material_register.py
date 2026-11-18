import frappe
from frappe import _
from frappe.model.document import Document


class ExcessMaterialRegister(Document):
	"""Made by the off-hire note and kept up to date by Excess Material Return Notes and Dismantling
	Entries (services/excess.py). Never entered or edited by hand."""

	def validate(self):
		if not self.flags.from_system:
			frappe.throw(_("The Excess Material Register is kept by the system. It is made when an off-hire note with excess is submitted."),
				title=_("Not Allowed"))

	def on_trash(self):
		if not self.flags.from_system:
			frappe.throw(_("An excess register is cancelled with its off-hire note, never deleted"), title=_("Not Allowed"))
