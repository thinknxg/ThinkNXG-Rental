"""v2.0: fill the new Rental Source Type / Rental Source fields from the old hire_order links."""
import frappe


def execute():
	frappe.db.sql(
		"""update `tabRental Contract` set naming_series = 'RC-.YYYY.-.#####'
		where naming_series like 'HC-%%'"""
	)
	# sites that ran the ERPNext setup wizard carry the old series as property setters
	frappe.db.sql(
		"""update `tabProperty Setter` set value = replace(value, 'HC-.YYYY.-.#####', 'RC-.YYYY.-.#####')
		where doc_type = 'Rental Contract' and field_name = 'naming_series' and value like '%%HC-.YYYY.-.#####%%'"""
	)
	frappe.clear_cache(doctype="Rental Contract")
	frappe.db.sql(
		"""update `tabRental Contract` set contract_type = 'Item Rental'
		where ifnull(contract_type, '') = ''"""
	)
	for doctype in ("Rental Contract", "Rental Material Reservation"):
		frappe.db.sql(
			f"""update `tab{doctype}` set source_type = 'Hire Order', source_document = hire_order
			where ifnull(hire_order, '') != '' and ifnull(source_document, '') = ''"""
		)
	for doctype in ("Rental Material Reservation", "Hire Delivery Order", "Rental Ownership Ledger"):
		frappe.db.sql(
			f"""update `tab{doctype}` t
			inner join `tabRental Contract` c on c.name = t.rental_contract
			set t.source_type = c.source_type, t.source_document = c.source_document
			where ifnull(c.source_document, '') != '' and ifnull(t.source_document, '') = ''"""
		)
