import frappe
from frappe.model.document import Document

from thinknxg_rental.services import vat


class RentalCompanyProfile(Document):
	def validate(self):
		vat.validate_profile(self)

	def on_update(self):
		frappe.clear_document_cache(self.doctype, self.name)

	@frappe.whitelist()
	def mark_reviewed(self, note: str | None = None):
		"""Finance confirms the treatment rules of this VAT country."""
		vat.mark_reviewed(self, note)
		return self.reviewed_on

	@frappe.whitelist()
	def setup_accounts(self):
		"""Create the deposit and advance liability accounts (under Current Liabilities) where they are empty."""
		frappe.only_for(("Accounts Manager", "System Manager"))
		from thinknxg_rental.services.setup import ensure_liability_accounts

		ensure_liability_accounts(self)
		self.save()
		return {f: self.get(f) for f in ("security_deposit_account", "customer_advance_account")}

	@frappe.whitelist()
	def add_default_rules(self):
		"""Fill an empty rule table with the starting rules (to be reviewed)."""
		if self.rules:
			frappe.throw(frappe._("The rule table is not empty"))
		for row in vat.default_rules(self.country):
			self.append("rules", row)
		self.save()
