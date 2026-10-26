import frappe
from frappe import _

from thinknxg_rental.portal.admin import build_admin_context
from thinknxg_rental.portal.entry import entry_url, get_entries, get_entry_type


def get_context(context):
	key = frappe.form_dict.get("type") or "lead"
	build_admin_context(context, key, _(get_entry_type(key)["plural"]))
	context.q = (frappe.form_dict.get("q") or "").strip()
	context.e = get_entries(key, frappe.form_dict.get("view"), context.q)
	context.key = key
	context.new_url = entry_url(key)
