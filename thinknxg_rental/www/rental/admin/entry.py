import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context
from thinknxg_rental.portal.entry import get_entry_type, get_form_boot


def get_context(context):
	key = frappe.form_dict.get("type") or "lead"
	name = frappe.form_dict.get("name")
	build_admin_context(context, key, name or _("New {0}").format(_(get_entry_type(key)["label"])))
	context.boot = get_form_boot(key, name, frappe.form_dict)
