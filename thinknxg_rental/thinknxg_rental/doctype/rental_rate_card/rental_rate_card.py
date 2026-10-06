import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from thinknxg_rental.services.utils import check_duplicate_items


class RentalRateCard(Document):
	def validate(self):
		if self.valid_from and self.valid_upto and getdate(self.valid_upto) < getdate(self.valid_from):
			frappe.throw(_("Valid Upto cannot be before Valid From"))
		check_duplicate_items(self)
