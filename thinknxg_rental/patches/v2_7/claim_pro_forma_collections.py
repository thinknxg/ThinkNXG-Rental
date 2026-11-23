"""2.7.2: a pro forma invoice counts the deposits and advances taken on its contract or hire order, also those
taken before it existed or was approved, and lists every receipt it counts (Payments Received)."""
import frappe

from thinknxg_rental.services import deposits


def execute():
	if not frappe.db.table_exists("Rental Pro Forma Payment"):
		return
	from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice.rental_pro_forma_invoice import refresh_payments

	for name in frappe.get_all("Rental Pro Forma Invoice", filters={"docstatus": 1}, pluck="name"):
		deposits.claim_collections(name)
		refresh_payments(name)
