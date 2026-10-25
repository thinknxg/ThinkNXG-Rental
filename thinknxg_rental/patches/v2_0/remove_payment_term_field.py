"""The single Payment Term link (nxg_payment_term) on Quotation, Sales Order and Sales Invoice was
dropped in favour of ERPNext's own Payment Terms Template; remove it from sites that had it."""
import frappe


def execute():
	for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
		name = f"{doctype}-nxg_payment_term"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
