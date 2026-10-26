import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_billing


def get_context(context):
	build_admin_context(context, "billing", _("Rental Billing"))
	context.q = (frappe.form_dict.get("q") or "").strip()
	context.g = get_billing(context.q)
