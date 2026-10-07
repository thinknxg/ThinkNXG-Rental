"""v2.0.2: earlier releases shipped the workspace and sidebar with an unchanged timestamp, so
Frappe skipped them on upgrade and left the old layout in place (no Rental Contract shortcut, no
Job Type Contracts section). Re-import both once, replacing whatever is stored."""
import os

import frappe
from frappe.modules.import_file import import_file_by_path


def execute():
	for parts in (
		("thinknxg_rental", "workspace", "thinknxg_rental", "thinknxg_rental.json"),
		("workspace_sidebar", "thinknxg_rental.json"),
	):
		path = frappe.get_app_path("thinknxg_rental", *parts)
		if os.path.exists(path):
			import_file_by_path(path, force=True)
	frappe.clear_cache()
