"""thinkNXG Rental Command Center (/rental/admin and every path under it).

The page is the shell of a single-page application (public/command_center). It renders for rental
staff only; everything it shows comes from command_center/api.py, which checks the user's roles and
permissions again on every call.
"""
from urllib.parse import quote

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		path = frappe.request.full_path if frappe.request else "/rental/admin"
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path.rstrip("?"))
		raise frappe.Redirect
	from thinknxg_rental.command_center import api
	from thinknxg_rental.command_center.registry import is_staff

	if not is_staff():
		raise frappe.PermissionError(_("The rental Command Center is for rental staff only."))
	context.no_cache = 1
	context.title = _("Command Center")
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.cc_boot = api.boot()
	context.lang = frappe.local.lang or "en"
	context.app_name = frappe.get_website_settings("app_name") or "thinkNXG"
	from thinknxg_rental import __version__

	context.asset_version = __version__
