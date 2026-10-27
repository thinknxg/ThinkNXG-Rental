import frappe
from frappe import _

from thinknxg_rental.portal.admin import REQUEST_TYPES, build_admin_context, get_admin_requests


def get_context(context):
	build_admin_context(context, "requests", _("Customer Requests"))
	context.q = (frappe.form_dict.get("q") or "").strip()
	context.request_type = frappe.form_dict.get("request_type") or ""
	context.request_types = REQUEST_TYPES
	context.view, context.requests = get_admin_requests(frappe.form_dict.get("view"), context.q, context.request_type)
