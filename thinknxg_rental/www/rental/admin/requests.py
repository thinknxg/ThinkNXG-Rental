import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context, get_admin_requests


def get_context(context):
	build_admin_context(context, "requests", _("Customer Requests"))
	context.view, context.requests = get_admin_requests(frappe.form_dict.get("view"))
