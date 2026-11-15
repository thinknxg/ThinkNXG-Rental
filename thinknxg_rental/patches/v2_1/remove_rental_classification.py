"""Stock + Asset (Rental Classification on Item) was withdrawn: remove its custom field.

Has Serial No on the Items is ERPNext's own setting and is left as it is: once an item has stock
transactions ERPNext does not allow it to change, and serial numbers work in the rental flow as before.
"""
import frappe


def execute():
	if frappe.db.exists("Custom Field", "Item-nxg_rental_classification"):
		frappe.delete_doc("Custom Field", "Item-nxg_rental_classification", ignore_permissions=True)
