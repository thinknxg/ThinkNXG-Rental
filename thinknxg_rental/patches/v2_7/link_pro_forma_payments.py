"""Deposits and advances collected on a contract or hire order before 2.7.1 were not linked to its pro forma
invoice, so the pro forma invoice did not show them as received. Link each one whose contract (or hire order)
had exactly one pro forma invoice dated on or before the collection, and refresh that pro forma invoice."""
import frappe

from thinknxg_rental.services import deposits


def execute():
	if not frappe.db.table_exists("Rental Contract Payment") or not frappe.db.table_exists("Rental Pro Forma Invoice"):
		return
	statuses = deposits.OPEN_PRO_FORMA + ("Converted to Sales Invoice",)
	touched = set()
	for r in frappe.get_all("Rental Contract Payment", filters={"docstatus": 1, "pro_forma_invoice": ["in", ("", None)],
			"transaction_type": ["in", (deposits.D_COLLECT, deposits.A_COLLECT)]},
			fields=["name", "customer", "rental_contract", "hire_order", "posting_date"]):
		pi = deposits.open_pro_forma(r.customer, r.rental_contract, r.hire_order, statuses, on_or_after=r.posting_date)
		if pi:
			frappe.db.set_value("Rental Contract Payment", r.name, "pro_forma_invoice", pi, update_modified=False)
			touched.add(pi)
	if touched:
		from thinknxg_rental.thinknxg_rental.doctype.rental_pro_forma_invoice.rental_pro_forma_invoice import refresh_payments

		for pi in touched:
			refresh_payments(pi)
