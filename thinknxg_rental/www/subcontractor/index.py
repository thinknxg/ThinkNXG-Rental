"""Subcontractor portal (/subcontractor and every path under it): the shell of a single-page application
(public/subcontractor_portal). Everything it shows comes from portal/subcontractor.py, which resolves the subcontractor
from the session on every call."""
from urllib.parse import quote

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		path = frappe.request.full_path if frappe.request else "/subcontractor"
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path.rstrip("?"))
		raise frappe.Redirect
	from thinknxg_rental.services import subcontract_portal as sp

	if not sp.accesses():
		raise frappe.PermissionError(_("This login has no subcontractor portal access. Ask your contact at the company to invite you."))
	from thinknxg_rental import __version__

	context.no_cache = 1
	context.title = _("Subcontractor Portal")
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.lang = frappe.local.lang or "en"
	context.asset_version = __version__
	context.company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
