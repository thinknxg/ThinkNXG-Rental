"""2.4.1: the first seed put an instruction for administrators ("Choose the item group to show, then
tick Show.") in the subtitle of the two Category Products sections, where visitors could read it once
the section was switched on. Remove it where it was left unchanged."""
import frappe

HINT = "Choose the item group to show, then tick Show."


def execute():
	if not frappe.db.exists("DocType", "Rental Website Section"):
		return
	frappe.db.sql("update `tabRental Website Section` set subtitle = null where subtitle = %s", HINT)
	frappe.clear_cache(doctype="Rental Website Settings")
