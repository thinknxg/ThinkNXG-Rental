"""Roles and custom fields of the Subcontracting module. Runs on every migrate and is safe to repeat."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = ("Subcontracting Manager", "Subcontracting Executive", "Site Engineer", "Store Manager", "Project Manager",
	"Purchase Manager", "Accounts Manager", "Accounts User")


def custom_fields():
	sub = "eval:doc.is_subcontractor"
	return {
		"Supplier": [
			dict(fieldname="subcontractor_section", label="Subcontractor", fieldtype="Section Break", insert_after="supplier_details", collapsible=1),
			dict(fieldname="is_subcontractor", label="Is Subcontractor", fieldtype="Check", insert_after="subcontractor_section", in_standard_filter=1),
			dict(fieldname="subcontractor_category", label="Subcontractor Category", fieldtype="Data", insert_after="is_subcontractor", depends_on=sub),
			dict(fieldname="subcontractor_type", label="Provides", fieldtype="Select", options="Labour\nEquipment\nBoth",
				insert_after="subcontractor_category", depends_on=sub),
			dict(fieldname="approved_work_categories", label="Approved Work Categories", fieldtype="Small Text",
				insert_after="subcontractor_type", depends_on=sub, description="Job types or trades this subcontractor is approved for, one per line."),
			dict(fieldname="subcontractor_cb", fieldtype="Column Break", insert_after="approved_work_categories"),
			dict(fieldname="subcontractor_approval_status", label="Approval Status", fieldtype="Select",
				options="Pending\nApproved\nSuspended\nBlacklisted", default="Pending", insert_after="subcontractor_cb", depends_on=sub, in_standard_filter=1),
			dict(fieldname="default_retention_percentage", label="Default Retention %", fieldtype="Percent", insert_after="subcontractor_approval_status", depends_on=sub),
			dict(fieldname="performance_rating", label="Performance Rating", fieldtype="Rating", insert_after="default_retention_percentage", depends_on=sub),
			dict(fieldname="subcontract_terms", label="Subcontract Terms", fieldtype="Small Text", insert_after="performance_rating", depends_on=sub),
		],
		"Purchase Order": [
			dict(fieldname="subcontract_work_order", label="Subcontract Work Order", fieldtype="Link", options="Subcontract Work Order",
				insert_after="supplier_name", read_only=1, no_copy=1, search_index=1),
		],
		"Purchase Invoice": [
			dict(fieldname="subcontract_work_order", label="Subcontract Work Order", fieldtype="Link", options="Subcontract Work Order",
				insert_after="supplier_name", read_only=1, no_copy=1, search_index=1),
		],
		"Payment Entry": [
			dict(fieldname="subcontract_work_order", label="Subcontract Work Order", fieldtype="Link", options="Subcontract Work Order",
				insert_after="party_name", read_only=1, no_copy=1, search_index=1),
		],
	}


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def run():
	ensure_roles()
	create_custom_fields(custom_fields(), ignore_validate=True)
