import frappe
from frappe import _

from thinknxg_rental.portal.utils import build_context, get_contract_detail


def get_context(context):
	rp = build_context(context, "contracts", _("Hire Contract"))
	if rp.customers:
		context.c = get_contract_detail(frappe.form_dict.get("name"), rp.customers)
		context.title = _("Hire Contract {0}").format(context.c.doc.name)
