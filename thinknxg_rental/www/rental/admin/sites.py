import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_site_groups


def get_context(context):
	build_admin_context(context, "sites", _("Material at Site"))
	context.q = (frappe.form_dict.get("q") or "").strip()
	context.ownership = frappe.form_dict.get("ownership") or ""
	context.groups, context.totals = get_site_groups(context.q, context.ownership)
