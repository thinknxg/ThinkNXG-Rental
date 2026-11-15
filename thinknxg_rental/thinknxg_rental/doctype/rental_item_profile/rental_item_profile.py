import frappe
from frappe import _
from frappe.model.document import Document

from thinknxg_rental.services.item_rental import validate_profile_charges


class RentalItemProfile(Document):
	def validate(self):
		if not frappe.get_cached_value("Item", self.item, "is_stock_item"):
			frappe.throw(_("{0} must have Maintain Stock enabled to be rented").format(self.item))
		validate_profile_charges(self)
