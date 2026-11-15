"""Public rental website: default sections, cards, links and texts (empty tables only; safe to rerun)."""
import frappe


def execute():
	frappe.reload_doc("thinknxg_rental", "doctype", "rental_website_settings")
	from thinknxg_rental.thinknxg_rental.doctype.rental_website_settings.rental_website_settings import seed_defaults

	seed_defaults()
