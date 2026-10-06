import frappe
from frappe import _
from frappe.utils import flt

from thinknxg_rental.portal.utils import build_context, get_contracts, get_requests


def get_context(context):
	rp = build_context(context, "requests", _("Requests"))
	if not rp.customers:
		return
	context.requests = get_requests(rp.customers, limit=100)
	live = get_contracts(rp.customers, live_only=True)
	context.live_contracts = live
	context.boot = {
		"customer": rp.preview_customer,
		"new": frappe.form_dict.get("new") or "",
		"contract": frappe.form_dict.get("contract") or "",
		"has_material": any(flt(c.total_at_site_qty) > 0 for c in live),
	}
