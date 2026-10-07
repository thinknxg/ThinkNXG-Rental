"""v2.0: the rental agreement DocType "Hire Order Contract" becomes "Rental Contract", so that the
name "Hire Order Contract" can be used for the new job type order. Runs before model sync, while
the old DocType is still in place. Existing documents keep their numbers (HC-...)."""
import frappe

RENAMES = (
	("Hire Order Contract", "Rental Contract"),
	("Hire Contract Item", "Rental Contract Item"),
	("Hire Contract Extension", "Rental Contract Extension"),
)
LINKED = (
	"Rental Material Reservation", "Hire Delivery Order", "Hire Off-Hire Note", "Rental Return Inspection",
	"Rental Damage Settlement", "Rental Billing Schedule", "Rental Ownership Ledger", "Cross Hire Order",
	"Rental Portal Request",
)
CUSTOM = ("Sales Invoice", "Purchase Order", "Stock Entry")


def execute():
	# only an old-style contract has billing fields; a fresh v2 install has nothing to convert
	is_old = frappe.db.exists("DocType", "Hire Order Contract") and frappe.db.exists(
		"DocField", {"parent": "Hire Order Contract", "fieldname": "billing_cycle"}
	)
	if not is_old or frappe.db.exists("DocType", "Rental Contract"):
		return

	for old, new in RENAMES:
		if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
			frappe.rename_doc("DocType", old, new, force=True)

	for doctype in LINKED:
		if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, "hire_contract"):
			if not frappe.db.has_column(doctype, "rental_contract"):
				frappe.db.rename_column(doctype, "hire_contract", "rental_contract")

	for doctype in CUSTOM:
		if frappe.db.has_column(doctype, "nxg_hire_contract") and not frappe.db.has_column(doctype, "nxg_rental_contract"):
			frappe.db.rename_column(doctype, "nxg_hire_contract", "nxg_rental_contract")
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": "nxg_hire_contract"})
		if name:
			frappe.db.delete("Custom Field", {"name": name})

	if frappe.db.table_exists("Rental Portal Request"):
		frappe.db.sql(
			"update `tabRental Portal Request` set reference_doctype = 'Rental Contract' where reference_doctype = 'Hire Order Contract'"
		)
	frappe.clear_cache()
