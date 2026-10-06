import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_admin_contracts


def get_context(context):
	build_admin_context(context, "contracts", _("Hire Contracts"))
	context.q = (frappe.form_dict.get("q") or "").strip()
	context.view, context.contracts = get_admin_contracts(frappe.form_dict.get("view"), context.q)
