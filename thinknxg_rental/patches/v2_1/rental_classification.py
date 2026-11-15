"""Items that already have serial numbers are Stock + Asset (their units are already identified)."""
import frappe


def execute():
	# patches run before after_migrate makes the custom fields
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from thinknxg_rental.services.setup import get_custom_fields

	create_custom_fields({"Item": get_custom_fields()["Item"]}, ignore_validate=True)
	frappe.db.sql(
		"""update `tabItem` set nxg_rental_classification = if(is_stock_item = 1 and has_serial_no = 1, 'Stock + Asset', 'Stock')
		where ifnull(nxg_rental_classification, '') = '' or (is_stock_item = 1 and has_serial_no = 1)"""
	)
