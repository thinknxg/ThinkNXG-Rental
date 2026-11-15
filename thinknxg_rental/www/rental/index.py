"""thinkNXG Rental customer Command Center (/rental and every path under it except /rental/admin).

The page is the shell of a single-page application (public/customer_portal). Guests are sent to the
login page; rental staff can preview a customer with ?customer=<name>. Everything shown comes from
portal/customer.py, which resolves the customer from the session user on every call.
"""
from urllib.parse import quote

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		path = frappe.request.full_path if frappe.request else "/rental"
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path.rstrip("?"))
		raise frappe.Redirect(302)  # temporary: the page exists once signed in
	from thinknxg_rental import __version__
	from thinknxg_rental.portal.customer import boot

	context.no_cache = 1
	context.title = _("thinkNXG Rental")
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.cp_boot = boot(frappe.form_dict.get("customer"))
	context.lang = frappe.local.lang or "en"
	context.asset_version = __version__
