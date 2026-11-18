"""thinkNXG branding on the framework's own screens, set from this app.

The framework and ERP apps draw some screens themselves: the login and password pages, the desk's
browser tab and logo, the Help menu. Where those show the old product names this app replaces them,
but only where the site still has the framework's untouched default; a value an administrator chose
is never overwritten. Runs after every migrate (hooks.after_migrate), so it is idempotent.

The favicon, splash image and "Powered by" footer of web pages come from hooks.website_context, and
the thinkNXG Support entry of the Help menu from hooks.standard_help_items.
"""
import frappe

LOGO = "/assets/thinknxg_rental/images/logo.svg"
APP_NAME = "thinkNXG"
# the framework's defaults that carry the old names
OLD_APP_NAMES = ("", "Frappe", "ERPNext", "Frappe Framework")
OLD_HELP_ROUTES = ("frappe.io/support", "frappe.io/erpnext", "docs.erpnext.com", "docs.frappe.io", "discuss.frappe.io", "discuss.erpnext.com")


def apply():
	app_name()
	navbar()
	frappe.clear_cache()


def app_name():
	"""System Settings > App Name (the desk's tab title and the name in system e-mails). The desk reads it from
	the system defaults, which System Settings keeps in step on save; set both, as saving does."""
	current = frappe.db.get_single_value("System Settings", "app_name") or ""
	if current in OLD_APP_NAMES:
		frappe.db.set_single_value("System Settings", "app_name", APP_NAME)
		current = APP_NAME
	if (frappe.db.get_default("app_name") or "") != current:
		frappe.db.set_default("app_name", current)


def navbar():
	"""Navbar Settings: the desk and login logo when none was chosen (else the ERP app's logo shows), and
	the framework's support links hidden (the thinkNXG Support entry takes their place)."""
	settings = frappe.get_single("Navbar Settings")
	changed = False
	if not settings.app_logo and not frappe.db.get_single_value("Website Settings", "app_logo"):
		settings.app_logo = LOGO
		changed = True
	for row in settings.help_dropdown:
		if not row.hidden and any(old in (row.route or "") for old in OLD_HELP_ROUTES):
			row.hidden = 1
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()
