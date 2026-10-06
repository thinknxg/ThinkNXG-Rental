import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_stock_rows


def get_context(context):
	build_admin_context(context, "yard", _("Rental Yard"))
	context.category = frappe.form_dict.get("category") or ""
	context.categories = ["Formwork", "Scaffolding", "Shoring / Props", "Accessories", "Other"]
	if context.category not in context.categories:
		context.category = ""
	context.rows = get_stock_rows({"category": context.category} if context.category else {})
